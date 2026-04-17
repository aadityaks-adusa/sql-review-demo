#!/usr/bin/env python3
"""
AI SQL Reviewer — Coreservices Database Deployments
====================================================
End-to-end AI review: no hardcoded rules, no regex. All SQL analysis is delegated to GPT-4o.

Architecture (borrowed from Gemini CI/CD Bot pattern + Reviewbot):
  GitHub Actions (CI)
    → checkout + get diff
    → classify files by path (Python — path strings only, no SQL parsing)
    → send full diff + sql_review_prompt.md (all rules in plain English) to GPT-4o
    → parse structured JSON response  { overall_tier, summary, findings[] }
    → write /tmp/review.json  →  enforce.py posts inline comments + label + gate

To add/remove/change a rule:
  Edit .github/instructions/sql.instructions.md  (one table row = one rule)
  No Python, no regex, no code changes required.

Python's role:
  1. git diff (changed SQL files)
  2. classify each file by filename/path only
  3. call GitHub Models API with retry
  4. write review.json + GitHub Actions step summary

Environment:
  GITHUB_TOKEN      — set automatically by Actions (models: read permission required)
  BASE_SHA          — github.event.pull_request.base.sha
  HEAD_SHA          — github.event.pull_request.head.sha
  SQL_REVIEW_OUTPUT — output path (default: /tmp/review.json)
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
MODEL               = "openai/gpt-4o"
GITHUB_API_VERSION  = "2026-03-10"
MAX_DIFF_CHARS      = 30_000   # cap to stay within context window
TEMPERATURE         = 0.1      # near-deterministic for compliance review
MAX_RETRIES         = 3        # retry on 429/503
RETRY_WAIT_S        = 65       # GitHub Models free tier: 10 req/min → wait 65s on 429

SCRIPT_DIR  = Path(__file__).parent
PROMPT_FILE = SCRIPT_DIR / "sql_review_prompt.md"
OUTPUT_FILE = Path(os.environ.get("SQL_REVIEW_OUTPUT", "/tmp/review.json"))


# ---------------------------------------------------------------------------
# File-type classification (path only — no SQL parsing)
# ---------------------------------------------------------------------------

def classify_file(path: str) -> str:
    """
    Classify a SQL file by its name and path — no SQL content inspection.
    Returns one of: DDL_versioned | DDL_repeatable | DML | DML_production | OTHER
    """
    p = Path(path)
    name = p.name
    parts = [part.lower() for part in p.parts]

    is_prod = "prd" in parts and not ("nonprd" in parts)
    in_dml_folder = any(part.endswith("_dml") for part in parts)
    is_dm_file = name.startswith("DM")

    if in_dml_folder or is_dm_file:
        return "DML_production" if is_prod else "DML"
    if name.startswith("V") and name.endswith(".sql"):
        return "DDL_versioned"
    if name.startswith("R__") and name.endswith(".sql"):
        return "DDL_repeatable"
    return "OTHER"


# ---------------------------------------------------------------------------
# Git diff helpers
# ---------------------------------------------------------------------------

def get_changed_sql_files() -> list[str]:
    base = os.environ.get("BASE_SHA", "HEAD~1")
    head = os.environ.get("HEAD_SHA", "HEAD")
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACM", base, head],
            capture_output=True, text=True, check=True,
        )
        return [f for f in result.stdout.strip().splitlines() if f.endswith(".sql")]
    except subprocess.CalledProcessError as exc:
        print(f"[ai_sql_reviewer] git diff failed: {exc.stderr}", file=sys.stderr)
        return []


def get_diff(base: str, head: str) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--unified=5", base, head, "--", "*.sql"],
            capture_output=True, text=True, check=True,
        )
        diff = result.stdout
        if len(diff) > MAX_DIFF_CHARS:
            diff = diff[:MAX_DIFF_CHARS] + "\n\n[diff truncated — review full file for context]"
        return diff
    except subprocess.CalledProcessError as exc:
        print(f"[ai_sql_reviewer] git diff (content) failed: {exc.stderr}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# System prompt loader
# ---------------------------------------------------------------------------

def load_system_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    # Fallback inline prompt if file is missing
    return (
        "You are a strict SQL migration code reviewer for a PostgreSQL + Flyway repository. "
        "Classify every issue as HARD_BLOCK or DBA_REVIEW. "
        "Respond ONLY with valid JSON matching the schema: "
        '{"overall_tier":"HARD_BLOCK|DBA_REVIEW|CLEAN","summary":"string","findings":['
        '{"file":"string","line":0,"pattern":"string","tier":"HARD_BLOCK|DBA_REVIEW","risk":"string","fix":"string"}]}'
    )


# ---------------------------------------------------------------------------
# GitHub Models API call
# ---------------------------------------------------------------------------

def call_ai_reviewer(files_info: list[dict], diff: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return _safety_block(files_info, "GITHUB_TOKEN not set — cannot call AI reviewer")

    system_prompt = load_system_prompt()

    files_block = "\n".join(
        f"  - {f['path']}  [type: {f['type']}]" for f in files_info
    )
    user_message = (
        f"Changed SQL files:\n{files_block}\n\n"
        f"Full git diff:\n```diff\n{diff}\n```\n\n"
        "Review the diff and respond with valid JSON only."
    )

    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    # Retry loop — handles 429 (rate limit) and 503 (transient error)
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(
            GITHUB_MODELS_ENDPOINT,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                return json.loads(content)
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            if exc.code in (429, 503) and attempt < MAX_RETRIES:
                print(
                    f"[ai_sql_reviewer] HTTP {exc.code} on attempt {attempt}/{MAX_RETRIES} "
                    f"— waiting {RETRY_WAIT_S}s before retry...",
                    file=sys.stderr,
                )
                time.sleep(RETRY_WAIT_S)
                continue
            print(f"[ai_sql_reviewer] API HTTP error {exc.code}: {err[:300]}", file=sys.stderr)
            return _safety_block(files_info, f"GitHub Models API returned HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001
            print(f"[ai_sql_reviewer] API call failed: {exc}", file=sys.stderr)
            return _safety_block(files_info, f"AI reviewer unavailable: {exc}")

    return _safety_block(files_info, f"All {MAX_RETRIES} retry attempts failed")


def _safety_block(files_info: list[dict], reason: str) -> dict:
    """Return a HARD_BLOCK review when the AI is unavailable. Fail closed, not open."""
    return {
        "overall_tier": "HARD_BLOCK",
        "summary": (
            f"AI review could not be completed: {reason}. "
            "Blocking as a precaution — manual DBA review required before merge."
        ),
        "findings": [
            {
                "file": f["path"],
                "line": 0,
                "pattern": "AI review unavailable",
                "tier": "HARD_BLOCK",
                "risk": reason,
                "fix": "Ensure GITHUB_TOKEN has 'models: read' permission and retry.",
            }
            for f in files_info
        ],
    }


# ---------------------------------------------------------------------------
# GitHub Actions step summary
# ---------------------------------------------------------------------------

_SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}
_TIER_ICON     = {"HARD_BLOCK": "🚫", "DBA_REVIEW": "⚠️", "CLEAN": "✅"}


def build_step_summary(review: dict, files_info: list[dict]) -> str:
    tier     = review.get("overall_tier", "UNKNOWN")
    summary  = review.get("summary", "")
    findings = review.get("findings", [])

    tier_icon = _TIER_ICON.get(tier, "❓")
    lines = [
        f"## {tier_icon} SQL AI Review — {tier}",
        "",
        f"| Model | Files reviewed | Findings |",
        f"|---|---|---|",
        f"| `{MODEL}` | {len(files_info)} | {len(findings)} |",
        "",
        f"> {summary}" if summary else "",
        "",
    ]

    if findings:
        lines += [
            "### Findings",
            "",
            "| Severity | Tier | File | Line | Pattern | Confidence |",
            "|---|---|---|---|---|---|",
        ]
        for f in findings:
            sev  = f.get("severity", "HIGH")
            icon = _SEVERITY_ICON.get(sev, "🟠")
            conf = f.get("confidence", 0)
            conf_pct = f"{int(conf * 100)}%" if conf else "—"
            tier_tag = f.get("tier", "DBA_REVIEW")
            lines.append(
                f"| {icon} {sev} | {tier_tag} | `{f.get('file', '?')}` "
                f"| {f.get('line', '?')} | {f.get('pattern', '?')} | {conf_pct} |"
            )
        lines.append("")
    else:
        lines.append("No findings — SQL changes look clean. ✅")

    return "\n".join(lines)



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    base = os.environ.get("BASE_SHA", "HEAD~1")
    head = os.environ.get("HEAD_SHA", "HEAD")

    sql_files = get_changed_sql_files()
    if not sql_files:
        print("[ai_sql_reviewer] No SQL files changed — writing CLEAN review")
        review = {
            "overall_tier": "CLEAN",
            "summary": "No SQL files changed in this pull request.",
            "findings": [],
        }
        OUTPUT_FILE.write_text(json.dumps(review, indent=2), encoding="utf-8")
        _write_step_summary(build_step_summary(review, []))
        return

    files_info = [{"path": f, "type": classify_file(f)} for f in sql_files]
    print(f"[ai_sql_reviewer] Reviewing {len(files_info)} SQL file(s) via {MODEL}...")
    for fi in files_info:
        print(f"  {fi['type']:20s}  {fi['path']}")

    diff = get_diff(base, head)
    if not diff:
        review = _safety_block(files_info, "Could not retrieve git diff")
    else:
        review = call_ai_reviewer(files_info, diff)

    # Validate and normalise tier
    valid_tiers = {"HARD_BLOCK", "DBA_REVIEW", "CLEAN"}
    if review.get("overall_tier") not in valid_tiers:
        review["overall_tier"] = "HARD_BLOCK"
        review["summary"] = "AI returned an unexpected response structure. Blocking as a precaution."

    OUTPUT_FILE.write_text(json.dumps(review, indent=2), encoding="utf-8")
    print(f"[ai_sql_reviewer] Review written to {OUTPUT_FILE}")
    print(f"[ai_sql_reviewer] Overall tier: {review['overall_tier']}")

    _write_step_summary(build_step_summary(review, files_info))


def _write_step_summary(content: str) -> None:
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(content + "\n")


if __name__ == "__main__":
    main()
    sys.exit(0)  # enforce.py owns the exit code
