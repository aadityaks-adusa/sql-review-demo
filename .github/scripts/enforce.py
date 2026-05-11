#!/usr/bin/env python3
"""
Enforce — reads review.json → posts inline GitHub PR review → labels → exit code.
===================================================================================
Implements the "Copilot explains, CI enforces" pattern from the community.

Architecture (Gemini CI/CD Bot pattern adapted for GitHub Models):
  ai_sql_reviewer.py writes /tmp/review.json
  enforce.py reads it and:
    1. Builds one batched createReview call with ALL findings as inline diff comments
       (one comment per finding, anchored to exact diff line — like a senior engineer)
    2. Falls back to body-only if GitHub rejects any line numbers (422)
    3. Adds a label (sql-hard-block | dba-review-required | sql-scan-clean)
    4. Writes a step summary table for observability
    5. Exits 1 on HARD_BLOCK (CI gate) or 0 otherwise

Severity display (borrowed from Reviewbot / Gemini CI pattern):
  🔴 CRITICAL   — irreversible data loss (DELETE/UPDATE without WHERE)
  🟠 HIGH       — crash on retry (ADD COLUMN without IF NOT EXISTS)
  🟡 MEDIUM     — locking / destructive (ALTER TYPE, DROP, ALTER SEQUENCE)
  🔵 LOW        — policy / advisory (audit columns, PII)

Environment:
  GITHUB_TOKEN          — pull-requests: write + issues: write
  SQL_SCAN_REVIEW_FILE  — path to review.json (default: /tmp/review.json)
  PR_NUMBER             — pull request number
  REPO                  — owner/repo
  HEAD_SHA              — PR head commit SHA (required for inline anchoring)
"""

import json
import os
import sys
import urllib.request
import urllib.error

REVIEW_FILE = os.environ.get("SQL_SCAN_REVIEW_FILE", "/tmp/review.json")
GH_API      = "https://api.github.com"
TOKEN       = os.environ.get("GITHUB_TOKEN", "")
REPO        = os.environ.get("REPO", os.environ.get("GITHUB_REPOSITORY", ""))
PR_NUMBER   = os.environ.get("PR_NUMBER", "")
HEAD_SHA    = os.environ.get("HEAD_SHA", "")

# Severity → icon (borrowing from Gemini CI/CD Bot pattern)
_SEV_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}
_TIER_ICON = {"HARD_BLOCK": "🚫", "DBA_REVIEW": "⚠️", "CLEAN": "✅"}

FOOTER = (
    "\n\n---\n"
    "*[SQL AI Review](/.github/workflows) · GitHub Models GPT-4o · "
    "[Edit rules ↗](/.github/instructions/sql.instructions.md)*"
)


# ---------------------------------------------------------------------------
# GitHub API helper
# ---------------------------------------------------------------------------

def _request(method: str, path: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{GH_API}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[enforce] GitHub API {exc.code} on {method} {path}: {body[:400]}", file=sys.stderr)
        return exc.code, {}
    except Exception as exc:  # noqa: BLE001
        print(f"[enforce] Request failed: {exc}", file=sys.stderr)
        return 0, {}


def add_label(label: str) -> None:
    _request("POST", f"/repos/{REPO}/issues/{PR_NUMBER}/labels", {"labels": [label]})


# ---------------------------------------------------------------------------
# Inline comment body builder (one comment = one finding)
# Borrowing from Gemini CI/CD pattern: precise, actionable, copy-pasteable
# ---------------------------------------------------------------------------

def _inline_comment_body(finding: dict) -> str:
    sev   = finding.get("severity", "HIGH")
    tier  = finding.get("tier", "DBA_REVIEW")
    icon  = _SEV_ICON.get(sev, "🟠")
    tag   = "[HARD_BLOCK]" if tier == "HARD_BLOCK" else "[DBA_REVIEW]"
    conf  = finding.get("confidence", 0)
    conf_str = f" · confidence {int(conf * 100)}%" if conf else ""

    body  = f"{icon} **{tag} {finding.get('pattern', 'SQL issue')}**{conf_str}\n\n"
    body += finding.get("risk", "")

    fix = (finding.get("fix") or "").strip()
    if fix:
        body += f"\n\n**Suggested fix** (copy-paste ready):\n```sql\n{fix}\n```"

    body += FOOTER
    return body


# ---------------------------------------------------------------------------
# Review summary (top-level body — shown in Review tab)
# ---------------------------------------------------------------------------

def _review_summary(tier: str, summary: str, overflow_findings: list) -> str:
    icon  = _TIER_ICON.get(tier, "❓")
    lines = [f"## {icon} SQL AI Review — {tier}", "", f"> {summary}"]

    if tier == "CLEAN":
        lines.append(
            "\nSQL changes look good — all idempotency guards present, "
            "audit columns included. ✅"
        )

    # findings that couldn't go inline (line=0 or not in diff) go here
    for f in overflow_findings:
        sev  = f.get("severity", "HIGH")
        sev_icon = _SEV_ICON.get(sev, "🟠")
        lines += [
            "",
            f"### {sev_icon} `{f.get('file', '?')}` — line {f.get('line', '?')}",
            f"**{f.get('pattern', '?')}** — {f.get('risk', '')}",
        ]
        fix = (f.get("fix") or "").strip()
        if fix:
            lines += ["", f"```sql\n{fix}\n```"]

    lines.append(FOOTER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GitHub Actions step summary table
# ---------------------------------------------------------------------------

def _write_step_summary(tier: str, summary: str, findings: list) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not path:
        return
    icon = _TIER_ICON.get(tier, "❓")
    lines = [
        f"## {icon} SQL AI Review — {tier}",
        "",
        f"> {summary}",
        "",
    ]
    if findings:
        lines += [
            "| Severity | Tier | File | Line | Pattern | Confidence |",
            "|---|---|---|---|---|---|",
        ]
        for f in findings:
            sev      = f.get("severity", "HIGH")
            sev_icon = _SEV_ICON.get(sev, "🟠")
            conf     = f.get("confidence", 0)
            conf_pct = f"{int(conf * 100)}%" if conf else "—"
            lines.append(
                f"| {sev_icon} {sev} | {f.get('tier','?')} | `{f.get('file','?')}` "
                f"| {f.get('line','?')} | {f.get('pattern','?')} | {conf_pct} |"
            )
    else:
        lines.append("No findings. ✅")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Core: post inline review comments + a regular PR comment (NOT a formal review)
#
# Why not a formal review?
#   GitHub displays anyone who submits a review (even github-actions[bot]) as a
#   reviewer in the PR's "Reviewers" sidebar. We want Copilot to be the only
#   visible reviewer. So:
#     - Inline diff-line comments are posted via the "review comments" endpoint
#       (these show as inline annotations but don't make us a "reviewer")
#     - The summary + body-only findings go to the issues/comments endpoint
#       (regular PR comment, not a review)
#     - Tier-based label + CI exit code is what enforces the merge gate
# ---------------------------------------------------------------------------

def _post_inline_comment(finding: dict) -> int:
    """Post a single inline diff comment via the pull request comments API."""
    payload = {
        "body":      _inline_comment_body(finding),
        "commit_id": HEAD_SHA,
        "path":      finding["file"],
        "line":      finding["line"],
        "side":      "RIGHT",
    }
    status, _ = _request("POST", f"/repos/{REPO}/pulls/{PR_NUMBER}/comments", payload)
    return status


def _post_issue_comment(body: str) -> None:
    """Post a regular PR comment (does not add poster to reviewer list)."""
    _request("POST", f"/repos/{REPO}/issues/{PR_NUMBER}/comments", {"body": body})


def post_review(tier: str, summary: str, findings: list) -> None:
    # Inline findings = file + line; the rest go in the summary comment body
    inline = [f for f in findings if f.get("file") and (f.get("line") or 0) > 0]
    overflow = [f for f in findings if f not in inline]

    # 1. Post one inline diff comment per finding with a precise line number
    posted = 0
    if HEAD_SHA:
        for f in inline:
            status = _post_inline_comment(f)
            if 200 <= status < 300:
                posted += 1
            else:
                # Line not in diff range (422) — fall through to body
                overflow.append(f)
    else:
        # No commit_id → can't post inline; put everything in the body
        overflow = findings

    # 2. Post a single summary issue-comment (not a review) with any overflow
    _post_issue_comment(_review_summary(tier, summary, overflow))

    print(f"[enforce] Posted {posted} inline comment(s) + 1 summary comment "
          f"({len(overflow)} finding(s) in body)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not TOKEN or not REPO or not PR_NUMBER:
        missing = [k for k, v in {"GITHUB_TOKEN": TOKEN, "REPO": REPO, "PR_NUMBER": PR_NUMBER}.items() if not v]
        print(f"[enforce] Missing env vars: {missing}", file=sys.stderr)
        sys.exit(1)

    if not HEAD_SHA:
        print("[enforce] WARNING: HEAD_SHA not set — inline diff anchoring will be degraded", file=sys.stderr)

    # Load review.json — fail closed on any error (don't silently pass bad reviews)
    try:
        review = json.loads(open(REVIEW_FILE, encoding="utf-8").read())  # noqa: WPS515
    except FileNotFoundError:
        print(f"[enforce] {REVIEW_FILE} not found — blocking as precaution", file=sys.stderr)
        review = {
            "overall_tier": "HARD_BLOCK",
            "summary": "AI reviewer did not produce a review file. Check Step 1 logs. Blocking as a precaution.",
            "findings": [],
        }
    except json.JSONDecodeError as exc:
        print(f"[enforce] Malformed JSON: {exc}", file=sys.stderr)
        review = {
            "overall_tier": "HARD_BLOCK",
            "summary": "AI reviewer produced malformed output. Blocking as a precaution.",
            "findings": [],
        }

    tier     = review.get("overall_tier", "HARD_BLOCK")
    summary  = review.get("summary", "")
    findings = review.get("findings", [])

    post_review(tier, summary, findings)
    _write_step_summary(tier, summary, findings)

    if tier == "CLEAN":
        add_label("sql-scan-clean")
        print("[enforce] CLEAN — approved ✅")
        sys.exit(0)
    elif tier == "DBA_REVIEW":
        add_label("dba-review-required")
        print("[enforce] DBA_REVIEW — changes requested, DBA approval required before merge")
        sys.exit(0)   # CI green; DBA approval is the merge gate
    else:
        add_label("sql-hard-block")
        print("[enforce] HARD_BLOCK — changes requested, CI failing ❌")
        sys.exit(1)   # CI red → merge button disabled


if __name__ == "__main__":
    main()

