#!/usr/bin/env python3
"""
Process Copilot's PR review → apply label + status check.
==========================================================

Triggered by: pull_request_review event when Copilot submits a review.

Reads:
  - Copilot's review body (top-level summary)
  - Copilot's inline diff comments
Counts occurrences of:
  - [HARD_BLOCK]  → tier = HARD_BLOCK (CI red, merge blocked)
  - [DBA_REVIEW]  → tier = DBA_REVIEW (CI green + DBA approval needed)
  - neither       → tier = CLEAN (CI green, ready to merge)

Then:
  1. Removes any prior tier labels (sql-hard-block, dba-review-required, sql-scan-clean)
  2. Applies the new tier label
  3. Posts a commit status check 'SQL Review Tier' with state derived from tier

Environment:
  GITHUB_TOKEN       — pull-requests: write, statuses: write, issues: write
  REPO               — owner/repo
  PR_NUMBER          — pull request number
  HEAD_SHA           — PR head commit SHA (for status check)
  REVIEWER_LOGIN     — GitHub login of the bot/user whose review we're processing
                       (default: Copilot)
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error

GH_API         = "https://api.github.com"
TOKEN          = os.environ["GITHUB_TOKEN"]
REPO           = os.environ["REPO"]
PR_NUMBER      = os.environ["PR_NUMBER"]
HEAD_SHA       = os.environ["HEAD_SHA"]
REVIEWER_LOGIN = os.environ.get("REVIEWER_LOGIN", "Copilot")

TIER_LABELS = {
    "HARD_BLOCK": "sql-hard-block",
    "DBA_REVIEW": "dba-review-required",
    "CLEAN":      "sql-scan-clean",
}
ALL_TIER_LABELS = set(TIER_LABELS.values())

STATUS_CONTEXT = "SQL Review Tier"


def _request(method: str, path: str, payload=None) -> tuple[int, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
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
            body = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[copilot-review] {method} {path} → HTTP {exc.code}: {body[:200]}",
              file=sys.stderr)
        return exc.code, {}


def get_copilot_review_text() -> str:
    """Fetch the most recent review by REVIEWER_LOGIN + all its inline comments,
    concatenated as a single string we can scan for tier tags."""
    _, reviews = _request("GET", f"/repos/{REPO}/pulls/{PR_NUMBER}/reviews")
    if not isinstance(reviews, list):
        return ""

    # Pick the latest review submitted by the target reviewer
    bot_reviews = [
        r for r in reviews
        if (r.get("user") or {}).get("login", "").lower().startswith(REVIEWER_LOGIN.lower())
    ]
    if not bot_reviews:
        print(f"[copilot-review] No reviews found from {REVIEWER_LOGIN}", file=sys.stderr)
        return ""

    latest = bot_reviews[-1]
    review_id = latest["id"]
    body = latest.get("body") or ""

    # Fetch the inline comments belonging to this review
    _, comments = _request(
        "GET",
        f"/repos/{REPO}/pulls/{PR_NUMBER}/reviews/{review_id}/comments",
    )
    comment_bodies = [c.get("body", "") for c in comments] if isinstance(comments, list) else []

    return body + "\n\n" + "\n\n".join(comment_bodies)


def determine_tier(text: str) -> tuple[str, int, int]:
    """Return (tier, hard_block_count, dba_review_count)."""
    hard = len(re.findall(r"\[HARD[_ ]?BLOCK\]", text, re.IGNORECASE))
    dba  = len(re.findall(r"\[DBA[_ ]?REVIEW\]", text, re.IGNORECASE))
    if hard > 0:
        return "HARD_BLOCK", hard, dba
    if dba > 0:
        return "DBA_REVIEW", hard, dba
    return "CLEAN", 0, 0


def remove_old_tier_labels() -> None:
    _, current = _request("GET", f"/repos/{REPO}/issues/{PR_NUMBER}/labels")
    if not isinstance(current, list):
        return
    for label in current:
        name = label.get("name", "")
        if name in ALL_TIER_LABELS:
            _request("DELETE", f"/repos/{REPO}/issues/{PR_NUMBER}/labels/{name}")


def apply_label(label: str) -> None:
    _request("POST", f"/repos/{REPO}/issues/{PR_NUMBER}/labels", {"labels": [label]})


def post_status(state: str, description: str) -> None:
    """state ∈ {success, failure, pending}."""
    _request(
        "POST",
        f"/repos/{REPO}/statuses/{HEAD_SHA}",
        {
            "state": state,
            "context": STATUS_CONTEXT,
            "description": description[:140],  # GitHub limit
        },
    )


def main() -> None:
    text = get_copilot_review_text()
    if not text.strip():
        print(f"[copilot-review] {REVIEWER_LOGIN} review text empty — marking pending")
        post_status("pending", f"Waiting for {REVIEWER_LOGIN} to submit a review")
        sys.exit(0)

    tier, hard, dba = determine_tier(text)
    label = TIER_LABELS[tier]

    remove_old_tier_labels()
    apply_label(label)

    if tier == "HARD_BLOCK":
        post_status("failure", f"❌ {hard} HARD_BLOCK finding(s) — merge blocked")
        print(f"[copilot-review] HARD_BLOCK · hard={hard} dba={dba} · label={label}")
        sys.exit(0)
    elif tier == "DBA_REVIEW":
        post_status("success", f"⚠️  {dba} DBA_REVIEW finding(s) — DBA approval required")
        print(f"[copilot-review] DBA_REVIEW · dba={dba} · label={label}")
        sys.exit(0)
    else:
        post_status("success", "✅ No blocking findings — ready to merge")
        print(f"[copilot-review] CLEAN · label={label}")
        sys.exit(0)


if __name__ == "__main__":
    main()
