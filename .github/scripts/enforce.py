#!/usr/bin/env python3
"""
Enforce — reads review.json from ai_sql_reviewer.py and posts a formal GitHub PR review.

Actions taken:
  HARD_BLOCK  → POST REQUEST_CHANGES review, add sql-hard-block label, exit 1 (CI fails)
  DBA_REVIEW  → POST REQUEST_CHANGES review, add dba-review-required label, exit 0
  CLEAN       → POST APPROVE review, add sql-scan-clean label, exit 0

Environment variables:
  GITHUB_TOKEN          — token with pull-requests: write and issues: write
  SQL_SCAN_REVIEW_FILE  — path to review.json (default: /tmp/review.json)
  PR_NUMBER             — pull request number
  REPO                  — owner/repo string (e.g. ADUSA-Digital/pdl-coreservices-database-deployments)
"""

import json
import os
import sys
import urllib.request
import urllib.error

REVIEW_FILE = os.environ.get("SQL_SCAN_REVIEW_FILE", "/tmp/review.json")
GH_API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("REPO", os.environ.get("GITHUB_REPOSITORY", ""))
PR_NUMBER = os.environ.get("PR_NUMBER", "")


def gh_post(path: str, payload: dict) -> dict:
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
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[enforce] GitHub API {exc.code} on {path}: {body}", file=sys.stderr)
        return {}


def format_review_body(review: dict) -> str:
    tier = review.get("overall_tier", "UNKNOWN")
    summary = review.get("summary", "")
    findings = review.get("findings", [])

    emoji = {"HARD_BLOCK": "🚫", "DBA_REVIEW": "⚠️", "CLEAN": "✅"}.get(tier, "❓")
    lines = [
        f"## {emoji} SQL AI Review — {tier}",
        "",
        f"> {summary}",
        "",
    ]

    if findings:
        for f in findings:
            t_emoji = "🚫" if f.get("tier") == "HARD_BLOCK" else "⚠️"
            lines += [
                f"### {t_emoji} `{f.get('file', '?')}` — line {f.get('line', '?')}",
                f"**{f.get('pattern', '?')}**  ",
                f"{f.get('risk', '')}  ",
            ]
            fix = f.get("fix", "")
            if fix:
                lines += ["", "**Fix:**", "```sql", fix, "```"]
            lines.append("")
    else:
        lines.append("No findings — SQL changes look clean. All idempotency guards present.")

    lines += [
        "---",
        "*Reviewed by [SQL AI Review](/.github/workflows/sql-ai-review.yml) · "
        "GitHub Models GPT-4o · Rules: [copilot-instructions.md](/.github/copilot-instructions.md)*",
    ]
    return "\n".join(lines)


def add_label(label: str) -> None:
    gh_post(
        f"/repos/{REPO}/issues/{PR_NUMBER}/labels",
        {"labels": [label]},
    )


def post_review(event: str, body: str) -> None:
    gh_post(
        f"/repos/{REPO}/pulls/{PR_NUMBER}/reviews",
        {"event": event, "body": body},
    )


def main() -> None:
    if not TOKEN or not REPO or not PR_NUMBER:
        missing = [k for k, v in {"GITHUB_TOKEN": TOKEN, "REPO": REPO, "PR_NUMBER": PR_NUMBER}.items() if not v]
        print(f"[enforce] Missing env vars: {missing}", file=sys.stderr)
        sys.exit(1)

    try:
        review = json.loads(open(REVIEW_FILE, encoding="utf-8").read())
    except FileNotFoundError:
        print(f"[enforce] review file not found: {REVIEW_FILE}", file=sys.stderr)
        # Safety: treat missing file as a hard block
        review = {
            "overall_tier": "HARD_BLOCK",
            "summary": "Review file was not produced — AI reviewer may have crashed. Blocking as a precaution.",
            "findings": [],
        }
    except json.JSONDecodeError as exc:
        print(f"[enforce] Malformed review JSON: {exc}", file=sys.stderr)
        review = {
            "overall_tier": "HARD_BLOCK",
            "summary": "AI reviewer produced malformed output. Blocking as a precaution.",
            "findings": [],
        }

    tier = review.get("overall_tier", "HARD_BLOCK")
    body = format_review_body(review)

    if tier == "CLEAN":
        post_review("APPROVE", body)
        add_label("sql-scan-clean")
        print("[enforce] CLEAN — approved")
        sys.exit(0)

    elif tier == "DBA_REVIEW":
        post_review("REQUEST_CHANGES", body)
        add_label("dba-review-required")
        print("[enforce] DBA_REVIEW — requested changes, DBA required")
        sys.exit(0)  # CI check passes; DBA's approval gates the merge

    else:  # HARD_BLOCK or unknown
        post_review("REQUEST_CHANGES", body)
        add_label("sql-hard-block")
        print("[enforce] HARD_BLOCK — requested changes, CI failing")
        sys.exit(1)  # CI check fails → merge button disabled


if __name__ == "__main__":
    main()
