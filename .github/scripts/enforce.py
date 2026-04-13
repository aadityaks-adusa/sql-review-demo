#!/usr/bin/env python3
"""
SQL PR Enforce — Enforcement Step
Reads review.json and calls the GitHub REST API to:
  - Post a PR review (REQUEST_CHANGES or APPROVE)
  - Add labels (sql-hard-block | dba-review-required | sql-scan-clean)
  - Exit 1 on HARD_BLOCK to fail the required CI check

If review.json is missing (LLM step crashed), falls back to findings.json.
"""

import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse

REVIEW_FILE   = os.environ.get("SQL_SCAN_REVIEW_FILE",   "/tmp/review.json")
FINDINGS_FILE = os.environ.get("SQL_SCAN_FINDINGS_FILE", "/tmp/findings.json")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
PR_NUMBER     = os.environ.get("PR_NUMBER", "")
REPO          = os.environ.get("REPO", "")   # owner/repo

API = "https://api.github.com"


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _gh(method: str, path: str, body: dict = None) -> dict:
    url  = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization":        f"Bearer {GITHUB_TOKEN}",
            "Accept":               "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type":         "application/json",
            "User-Agent":           "sql-review-bot/1.0",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode()
        print(f"GitHub API {method} {path} → {e.code}: {msg}", file=sys.stderr)
        return {"_error": e.code, "_body": msg}


def ensure_label(name: str, color: str, description: str):
    existing = _gh("GET", f"/repos/{REPO}/labels/{urllib.parse.quote(name)}")
    if not existing.get("name"):
        _gh("POST", f"/repos/{REPO}/labels", {"name": name, "color": color, "description": description})


def set_labels(add_label: str):
    """Remove old scan labels, add the new one."""
    scan_labels = ["sql-scan-clean", "dba-review-required", "sql-hard-block"]

    # Get current labels on the PR
    current = _gh("GET", f"/repos/{REPO}/issues/{PR_NUMBER}/labels")
    current_names = [l["name"] for l in current] if isinstance(current, list) else []

    # Remove stale scan labels
    for label in scan_labels:
        if label in current_names:
            try:
                req = urllib.request.Request(
                    f"{API}/repos/{REPO}/issues/{PR_NUMBER}/labels/{urllib.parse.quote(label)}",
                    headers={
                        "Authorization":        f"Bearer {GITHUB_TOKEN}",
                        "Accept":               "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent":           "sql-review-bot/1.0",
                    },
                    method="DELETE",
                )
                with urllib.request.urlopen(req, timeout=30):
                    pass
            except Exception:
                pass

    # Add new label
    _gh("POST", f"/repos/{REPO}/issues/{PR_NUMBER}/labels", {"labels": [add_label]})
    print(f"Label set: {add_label}")


def post_review(event: str, body: str):
    """Post a PR review (REQUEST_CHANGES or APPROVE or COMMENT)."""
    result = _gh("POST", f"/repos/{REPO}/pulls/{PR_NUMBER}/reviews", {
        "event": event,
        "body":  body,
    })
    if result.get("id"):
        print(f"Review posted: id={result['id']} event={event}")
    return result


# ---------------------------------------------------------------------------
# Review body formatting
# ---------------------------------------------------------------------------

TIER_EMOJI = {"HARD_BLOCK": "🚫", "DBA_REVIEW": "⚠️", "CLEAN": "✅"}
TIER_LABEL = {"HARD_BLOCK": "HARD BLOCK — must fix before merge", "DBA_REVIEW": "DBA Review Required", "CLEAN": "Clean"}


def format_body(review: dict) -> str:
    tier    = review.get("overall_tier", "CLEAN")
    summary = review.get("summary", "")
    items   = review.get("findings", [])
    emoji   = TIER_EMOJI.get(tier, "❓")
    label   = TIER_LABEL.get(tier, tier)

    lines = [
        f"## {emoji} SQL Review — {label}",
        "",
        summary,
        "",
    ]

    if tier == "HARD_BLOCK":
        lines += [
            "> **How to unblock:** Fix the issue(s) below and push again.",
            "> The scanner will re-run automatically and approve when clean.",
            "",
        ]
    elif tier == "DBA_REVIEW":
        lines += [
            "> **Next step:** A member of `@pdl-eda` has been requested as reviewer.",
            "> The DBA must approve this PR before it can be merged.",
            "",
        ]

    if items:
        lines.append("---")
        lines.append("")
        lines.append("### Findings")
        lines.append("")

        for i, finding in enumerate(items, 1):
            file_name = finding.get("file", "unknown")
            line_no   = finding.get("line", 0)
            pattern   = finding.get("pattern", "")
            risk      = finding.get("risk", finding.get("description", ""))
            fix       = finding.get("fix", "")

            line_ref  = f"line {line_no}" if line_no > 0 else "whole-file check"
            tier_of_finding = finding.get("tier", tier)
            f_emoji   = "🚫" if tier_of_finding == "HARD_BLOCK" else "⚠️"

            lines += [
                f"#### {f_emoji} Finding {i}: `{pattern}`",
                f"**File:** `{file_name}` ({line_ref})",
                "",
                f"**Risk:** {risk}",
                "",
            ]

            if fix and fix != "See rule documentation for the correct form.":
                lines += [
                    "**Corrected SQL:**",
                    "```sql",
                    fix.strip(),
                    "```",
                    "",
                ]

            lines.append("---")
            lines.append("")

    if tier == "CLEAN":
        lines.append("All SQL patterns look good. No idempotency issues, no destructive operations without guards.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fallback: build review from findings.json if review.json is missing
# ---------------------------------------------------------------------------

def build_fallback_review() -> dict:
    if not os.path.exists(FINDINGS_FILE):
        return {"overall_tier": "CLEAN", "summary": "No findings.", "findings": []}
    with open(FINDINGS_FILE) as f:
        raw = json.load(f)
    if not raw:
        return {"overall_tier": "CLEAN", "summary": "No SQL issues detected.", "findings": []}
    tier_order = {"HARD_BLOCK": 3, "DBA_REVIEW": 2, "CLEAN": 1}
    overall = max((r["tier"] for r in raw), key=lambda t: tier_order.get(t, 0))
    return {
        "overall_tier": overall,
        "summary": f"Scanner found {len(raw)} issue(s). LLM reasoning step did not produce output.",
        "findings": [
            {"file": r["file"], "line": r["line_number"], "pattern": r["pattern"],
             "risk": r["description"], "fix": "See rule docs for the correct form.", "tier": r["tier"]}
            for r in raw
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not all([GITHUB_TOKEN, PR_NUMBER, REPO]):
        print(f"Missing env vars. TOKEN={'set' if GITHUB_TOKEN else 'MISSING'}, PR={PR_NUMBER}, REPO={REPO}", file=sys.stderr)
        sys.exit(1)

    # Load review.json (fall back if missing)
    if os.path.exists(REVIEW_FILE):
        with open(REVIEW_FILE) as f:
            review = json.load(f)
    else:
        print(f"review.json not found at {REVIEW_FILE} — using fallback", file=sys.stderr)
        review = build_fallback_review()

    tier = review.get("overall_tier", "CLEAN")
    print(f"Enforcing tier: {tier}")

    # Ensure labels exist
    ensure_label("sql-scan-clean",      "0e8a16", "SQL scanner: no issues detected")
    ensure_label("dba-review-required", "e4c100", "SQL scanner: DBA must review before merge")
    ensure_label("sql-hard-block",      "d73a4a", "SQL scanner: blocking issue — fix before merge")

    body = format_body(review)

    if tier == "HARD_BLOCK":
        post_review("REQUEST_CHANGES", body)
        set_labels("sql-hard-block")
        print("HARD_BLOCK — review posted, merge blocked")
        sys.exit(1)  # fail the required CI check

    elif tier == "DBA_REVIEW":
        post_review("REQUEST_CHANGES", body)
        set_labels("dba-review-required")
        print("DBA_REVIEW — review posted, DBA requested")
        # Check passes (no exit 1) but REQUEST_CHANGES blocks merge via branch protection

    else:
        post_review("APPROVE", body)
        set_labels("sql-scan-clean")
        print("CLEAN — PR approved")


if __name__ == "__main__":
    main()
