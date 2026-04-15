#!/usr/bin/env python3
"""
SQL AI Reviewer — AI-Only Pipeline
Coreservices Database Deployments

Replaces the old 3-step pipeline (sql_pr_scan.py → llm_reason.py → enforce.py)
with a single AI pass.

Design philosophy:
  - NO hardcoded SQL regex rules in Python
  - ALL SQL analysis is performed by GitHub Models (GPT-4o)
  - Python is responsible ONLY for: getting the diff, classifying file types
    from the path, calling the API, and writing review.json
  - Rules live in sql_review_prompt.md (human-readable, editable by anyone)
  - The same rules power GitHub Copilot code review via .github/copilot-instructions.md

Input:
  - Git diff between BASE_SHA and HEAD_SHA
  - sql_review_prompt.md (system prompt)

Output:
  - /tmp/review.json: {overall_tier, summary, findings: [{file, line, pattern, tier, risk, fix}]}
  - GitHub Actions step summary
  - Exit 0 always (enforce.py owns the exit code)

Fallback:
  - If the GitHub Models API is unavailable, the PR is blocked as a safety measure.
"""

import os
import re
import sys
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
BASE_SHA     = os.environ.get("BASE_SHA", "origin/main")
HEAD_SHA     = os.environ.get("HEAD_SHA", "HEAD")
REVIEW_FILE  = os.environ.get("SQL_REVIEW_OUTPUT", "/tmp/review.json")

# GitHub Models endpoint — uses built-in GITHUB_TOKEN, no extra secrets needed
MODELS_URL = "https://models.inference.ai.azure.com/chat/completions"
MODEL      = "gpt-4o"   # GPT-4o for stronger reasoning than gpt-4o-mini

SCRIPT_DIR  = Path(__file__).parent
PROMPT_FILE = SCRIPT_DIR / "sql_review_prompt.md"


# ---------------------------------------------------------------------------
# File type classification — path-based only, no SQL parsing
# ---------------------------------------------------------------------------

def classify_file(path: str) -> str:
    """
    Classify SQL file type from its path and filename only.
    This is the ONLY place Python makes decisions about SQL — purely from the filename.
    All actual SQL analysis is delegated to the AI.
    """
    p = Path(path)
    parts = p.parts
    name  = p.name

    # DML: lives in a *_dml/ folder OR filename starts with DM
    if any(part.endswith("_dml") for part in parts) or name.startswith("DM"):
        return "DML_production" if "prd" in parts else "DML"

    # Repeatable DDL: R__*.sql
    if name.startswith("R__") and name.endswith(".sql"):
        return "DDL_repeatable"

    # Versioned DDL: V*.sql
    if name.startswith("V") and name.endswith(".sql"):
        return "DDL_versioned"

    return "OTHER"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def get_changed_sql_files() -> list[str]:
    """Returns SQL files changed in this PR via git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", BASE_SHA, HEAD_SHA],
            capture_output=True, text=True, check=True,
        )
        return [f.strip() for f in result.stdout.splitlines() if f.strip().endswith(".sql")]
    except subprocess.CalledProcessError as e:
        print(f"ERROR: git diff failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def get_diff() -> str:
    """Returns the full unified diff for the PR, capped to stay within token budget."""
    try:
        result = subprocess.run(
            ["git", "diff", BASE_SHA, HEAD_SHA, "--unified=5"],
            capture_output=True, text=True, check=True,
        )
        diff = result.stdout
        if len(diff) > 25000:
            print(f"Diff truncated: {len(diff)} → 25000 chars")
            diff = diff[:25000] + "\n\n[... diff truncated — see full diff in GitHub UI ...]"
        return diff
    except subprocess.CalledProcessError:
        return ""


# ---------------------------------------------------------------------------
# System prompt loader
# ---------------------------------------------------------------------------

def load_system_prompt() -> str:
    """
    Load the SQL review rules from sql_review_prompt.md.
    This file is the single source of truth for all review rules.
    """
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")

    # Should not happen in normal operation — hard fail so we notice
    print(f"ERROR: System prompt not found at {PROMPT_FILE}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# GitHub Models API call
# ---------------------------------------------------------------------------

def call_ai_reviewer(files: list[str], diff: str) -> dict:
    """
    Calls GitHub Models (GPT-4o) with the full diff and file context.
    Returns the structured review dict.
    """
    system_prompt = load_system_prompt()

    # Build file context — all path-based, no SQL analysis
    file_context_lines = [
        f"  - {f}  [type: {classify_file(f)}]"
        for f in files
    ]
    file_context = "\n".join(file_context_lines)

    user_message = (
        f"## Changed SQL files in this PR\n\n"
        f"{file_context}\n\n"
        f"## Full git diff\n\n"
        f"```diff\n{diff}\n```\n\n"
        f"Review all SQL changes above according to the system prompt rules.\n"
        f"Classify each issue. If no issues found, return CLEAN with an empty findings array."
    )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.1,      # near-deterministic for consistent classification
        "max_tokens":  4000,
        "response_format": {"type": "json_object"},
    }

    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        MODELS_URL, data=data,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw     = json.loads(resp.read().decode("utf-8"))
            content = raw["choices"][0]["message"]["content"]
            review  = json.loads(content)
            tier    = review.get("overall_tier", "UNKNOWN")
            count   = len(review.get("findings", []))
            print(f"AI review complete: overall_tier={tier}, findings={count}")
            return review

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"GitHub Models API HTTP error {e.code}: {body}", file=sys.stderr)
        return _safety_block(files, f"GitHub Models API returned {e.code}")

    except json.JSONDecodeError as e:
        print(f"AI returned invalid JSON: {e}", file=sys.stderr)
        return _safety_block(files, "AI response was not valid JSON")

    except Exception as e:
        print(f"AI reviewer failed ({type(e).__name__}): {e}", file=sys.stderr)
        return _safety_block(files, str(e))


def _safety_block(files: list[str], reason: str) -> dict:
    """
    Returned when the AI is unavailable.
    Blocks the PR as a safety measure — an unreviewed SQL migration should not merge.
    """
    return {
        "overall_tier": "HARD_BLOCK",
        "summary": (
            f"🚨 AI SQL review could not complete: {reason}. "
            "The PR has been blocked as a safety measure. "
            "Re-push to trigger a fresh review, or contact the platform team if the issue persists."
        ),
        "findings": [
            {
                "file": f,
                "line": 0,
                "pattern": "AI review unavailable",
                "tier": "HARD_BLOCK",
                "risk": "The AI reviewer could not complete. SQL migrations must be reviewed before merging.",
                "fix": "Re-push to trigger a fresh workflow run.",
            }
            for f in files
        ],
    }


# ---------------------------------------------------------------------------
# GitHub Actions step summary
# ---------------------------------------------------------------------------

def build_step_summary(review: dict) -> str:
    tier     = review.get("overall_tier", "CLEAN")
    summary  = review.get("summary", "")
    findings = review.get("findings", [])

    emoji = {"HARD_BLOCK": "🚫", "DBA_REVIEW": "⚠️", "CLEAN": "✅"}.get(tier, "❓")
    label = {
        "HARD_BLOCK": "BLOCKED — must fix before merge",
        "DBA_REVIEW": "DBA Review Required",
        "CLEAN": "Clean — approved",
    }.get(tier, tier)

    lines = [
        f"## {emoji} SQL AI Review — {label}",
        "",
        summary,
        "",
        "---",
        "",
    ]

    if findings:
        lines += [
            "### Findings",
            "",
            "| File | Line | Pattern | Tier |",
            "|------|------|---------|------|",
        ]
        for f in findings:
            t_emoji = "🚫" if f.get("tier") == "HARD_BLOCK" else "⚠️"
            fname   = Path(f.get("file", "")).name
            line    = f.get("line", "—") or "—"
            pattern = f.get("pattern", "")
            tier_f  = f.get("tier", "")
            lines.append(f"| `{fname}` | {line} | **{pattern}** | {t_emoji} {tier_f} |")
    else:
        lines.append("No issues found. All SQL changes look good.")

    lines += [
        "",
        "---",
        "",
        "> *Reviewed by GitHub Models (GPT-4o) — AI-Only SQL Review*",
        "> *Rules: `.github/copilot-instructions.md` · System prompt: `.github/scripts/sql_review_prompt.md`*",
        "> *GitHub Copilot code review uses the same rules for inline PR comments.*",
    ]

    return "\n".join(lines)


def _write_step_summary(text: str):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not GITHUB_TOKEN:
        print("ERROR: GITHUB_TOKEN is required.", file=sys.stderr)
        sys.exit(1)

    files = get_changed_sql_files()

    if not files:
        print("No SQL files changed in this PR.")
        review = {
            "overall_tier": "CLEAN",
            "summary": "No SQL files changed in this PR.",
            "findings": [],
        }
        with open(REVIEW_FILE, "w", encoding="utf-8") as fh:
            json.dump(review, fh, indent=2)
        _write_step_summary("## ✅ SQL AI Review — Clean\n\nNo SQL files changed in this PR.")
        return

    print(f"Reviewing {len(files)} SQL file(s):")
    for f in files:
        print(f"  {f}  [{classify_file(f)}]")

    diff   = get_diff()
    review = call_ai_reviewer(files, diff)

    # Write review.json for enforce.py
    with open(REVIEW_FILE, "w", encoding="utf-8") as fh:
        json.dump(review, fh, indent=2)
    print(f"Written: {REVIEW_FILE}")

    # Write step summary
    _write_step_summary(build_step_summary(review))

    # Exit 0 always — enforce.py owns the exit code and PR blocking decision
    sys.exit(0)


if __name__ == "__main__":
    main()
