#!/usr/bin/env python3
"""
SQL PR Reason — LLM Step
Reads findings.json + raw git diff, calls GitHub Models API (gpt-4o-mini),
outputs review.json with overall_tier, PR comment body, and per-finding explanations.

Falls back to structured scanner output if the API is unavailable.
"""

import os
import re
import sys
import json
import subprocess
import urllib.request
import urllib.error

FINDINGS_FILE = os.environ.get("SQL_SCAN_FINDINGS_FILE", "/tmp/findings.json")
REVIEW_FILE   = os.environ.get("SQL_SCAN_REVIEW_FILE",   "/tmp/review.json")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
BASE_SHA      = os.environ.get("BASE_SHA", "origin/main")
HEAD_SHA      = os.environ.get("HEAD_SHA", "HEAD")

# GitHub Models endpoint — uses GITHUB_TOKEN, no extra secrets needed
MODELS_URL = "https://models.inference.ai.azure.com/chat/completions"
MODEL      = "gpt-4o-mini"

SYSTEM_PROMPT = """You are a senior PostgreSQL DBA reviewing Flyway SQL migration files for a large retail enterprise.

Context:
- Migration engine: Flyway — all SQL runs inside a transaction; retries are possible
- File types: V*.sql = versioned DDL (runs once), R__*.sql = repeatable DDL, DM*.sql = DML only
- Environments: nonprd (dev/qa/stage) and prd (production)

An automated scanner has already found specific violations. Your job is ONLY to:
1. Explain WHY each finding is risky in 1-2 plain-English sentences
2. Provide the EXACT corrected SQL as a fenced ```sql code block```

Rules:
- Never suggest CREATE INDEX CONCURRENTLY — Flyway transactions forbid it
- For ADD COLUMN, always use: ALTER TABLE IF EXISTS <schema>.<table> ADD COLUMN IF NOT EXISTS <col> <type>
- For CREATE TABLE, always add IF NOT EXISTS
- For CREATE INDEX, always add IF NOT EXISTS
- Audit columns required on all new tables: audt_cr_dt_tm, audt_cr_id, audt_upd_dt_tm, audt_upd_id

Respond with ONLY valid JSON — no markdown fences, no explanation outside the JSON:
{
  "overall_tier": "HARD_BLOCK" | "DBA_REVIEW" | "CLEAN",
  "summary": "1-2 sentence overall assessment",
  "findings": [
    {
      "file": "<path>",
      "line": <number>,
      "pattern": "<pattern name>",
      "risk": "<1-2 sentence plain-English risk explanation>",
      "fix": "<corrected SQL — complete statement>"
    }
  ]
}"""


def get_diff() -> str:
    try:
        result = subprocess.run(
            ["git", "diff", BASE_SHA, HEAD_SHA, "--unified=3"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout[:10000]  # cap to stay within token budget
    except subprocess.CalledProcessError:
        return ""


def call_github_models(findings: list, diff: str) -> dict:
    if not findings:
        return {"overall_tier": "CLEAN", "summary": "No SQL issues detected. All changes look good.", "findings": []}

    tier_order = {"HARD_BLOCK": 3, "DBA_REVIEW": 2, "CLEAN": 1}
    overall = max((f["tier"] for f in findings), key=lambda t: tier_order.get(t, 0))

    user_message = (
        f"Scanner findings (JSON):\n{json.dumps(findings, indent=2)}\n\n"
        f"Git diff (for context):\n{diff}"
    )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.1,
        "max_tokens": 2500,
        "response_format": {"type": "json_object"},
    }

    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        MODELS_URL,
        data=data,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw      = json.loads(resp.read().decode("utf-8"))
            content  = raw["choices"][0]["message"]["content"]
            reviewed = json.loads(content)
            print(f"LLM response: tier={reviewed.get('overall_tier')}, "
                  f"findings={len(reviewed.get('findings', []))}")
            return reviewed
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"GitHub Models API error {e.code}: {body}", file=sys.stderr)
        return _fallback_review(findings, overall)
    except Exception as e:
        print(f"LLM call failed ({type(e).__name__}): {e}", file=sys.stderr)
        return _fallback_review(findings, overall)


def _fallback_review(findings: list, overall_tier: str) -> dict:
    """Structured review from raw scanner output — used when LLM API is unavailable."""
    print("Using fallback review (scanner output only, no LLM reasoning)", file=sys.stderr)
    return {
        "overall_tier": overall_tier,
        "summary": (
            f"Scanner found {len(findings)} issue(s). "
            "LLM reasoning unavailable — raw scanner findings shown below."
        ),
        "findings": [
            {
                "file":    f["file"],
                "line":    f["line_number"],
                "pattern": f["pattern"],
                "risk":    f["description"],
                "fix":     "See rule documentation for the correct form.",
            }
            for f in findings
        ],
    }


def main():
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set", file=sys.stderr)
        # Write empty CLEAN review so enforce.py doesn't crash
        with open(REVIEW_FILE, "w") as f:
            json.dump({"overall_tier": "CLEAN", "summary": "GITHUB_TOKEN missing — skipping LLM step.", "findings": []}, f)
        sys.exit(0)

    if not os.path.exists(FINDINGS_FILE):
        print(f"findings.json not found at {FINDINGS_FILE} — writing CLEAN", file=sys.stderr)
        with open(REVIEW_FILE, "w") as f:
            json.dump({"overall_tier": "CLEAN", "summary": "No SQL findings.", "findings": []}, f)
        sys.exit(0)

    with open(FINDINGS_FILE) as f:
        findings = json.load(f)

    print(f"Loaded {len(findings)} finding(s) from {FINDINGS_FILE}")
    diff = get_diff()
    print(f"Diff context: {len(diff)} chars")
    print(f"Calling GitHub Models ({MODEL})...", flush=True)

    review = call_github_models(findings, diff)

    with open(REVIEW_FILE, "w") as f:
        json.dump(review, f, indent=2)
    print(f"review.json written → {REVIEW_FILE}")


if __name__ == "__main__":
    main()
