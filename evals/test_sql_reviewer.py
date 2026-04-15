#!/usr/bin/env python3
"""
SQL AI Reviewer — Evaluation Suite
===================================
Tests that the AI reviewer (GitHub Models GPT-4o + sql_review_prompt.md) correctly
classifies known SQL violations.

This is an "AI testing AI" evaluation (LLM-as-judge) with deterministic expected outputs
for well-known, clearly-defined SQL antipatterns.

Usage:
    # With GitHub token (runs real API calls):
    export GITHUB_TOKEN=<your-token>
    pytest evals/test_sql_reviewer.py -v

    # In GitHub Actions (token is auto-set):
    pytest evals/test_sql_reviewer.py -v --tb=short

    # Skip slow API tests:
    pytest evals/test_sql_reviewer.py -v -m "not slow"

Cost: Each test case makes 1 GitHub Models API call (~$0 — included in Copilot subscription).
Runtime: ~2-5 seconds per test. Full suite: ~30-60 seconds.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
MODELS_URL   = "https://models.inference.ai.azure.com/chat/completions"
MODEL        = "gpt-4o"

EVALS_DIR   = Path(__file__).parent
FIXTURES    = EVALS_DIR / "fixtures"
PROMPT_FILE = EVALS_DIR.parent / ".github" / "scripts" / "sql_review_prompt.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_system_prompt() -> str:
    if not PROMPT_FILE.exists():
        pytest.fail(f"System prompt not found: {PROMPT_FILE}")
    return PROMPT_FILE.read_text(encoding="utf-8")


def classify_file_type(path: Path) -> str:
    """Mirror of ai_sql_reviewer.py classify_file() — path-based only."""
    name  = path.name
    parts = path.parts
    if any(p.endswith("_dml") for p in parts) or name.startswith("DM"):
        return "DML"
    if name.startswith("R__") and name.endswith(".sql"):
        return "DDL_repeatable"
    if name.startswith("V") and name.endswith(".sql"):
        return "DDL_versioned"
    return "OTHER"


def call_ai_reviewer(sql_content: str, file_name: str) -> dict:
    """
    Directly calls the GitHub Models API with a single SQL fixture.
    Returns the structured review dict.
    """
    system_prompt = load_system_prompt()
    file_type     = classify_file_type(Path(file_name))

    user_message = (
        f"## Changed SQL files in this PR\n\n"
        f"  - {file_name}  [type: {file_type}]\n\n"
        f"## Full git diff\n\n"
        f"```diff\n{sql_content}\n```\n\n"
        f"Review the SQL above. Return your classification as JSON."
    )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
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

    with urllib.request.urlopen(req, timeout=90) as resp:
        raw     = json.loads(resp.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
        return json.loads(content)


# ---------------------------------------------------------------------------
# Fixtures / Parametrize
# ---------------------------------------------------------------------------

# Each entry: (fixture_path_relative_to_FIXTURES, expected_tier, description)
TEST_CASES = [
    # Hard block cases
    ("hard_block/V_add_column_no_guard.sql",    "HARD_BLOCK", "ADD COLUMN without IF NOT EXISTS"),
    ("hard_block/V_delete_no_where.sql",         "HARD_BLOCK", "DELETE without WHERE"),
    ("hard_block/V_update_no_where.sql",         "HARD_BLOCK", "UPDATE without WHERE"),
    ("hard_block/V_truncate_versioned.sql",      "HARD_BLOCK", "TRUNCATE in versioned migration"),
    ("hard_block/DM1.0.0__ddl_in_dml.sql",      "HARD_BLOCK", "DDL inside DML file"),

    # DBA review cases
    ("dba_review/V_alter_column_type.sql",       "DBA_REVIEW", "ALTER COLUMN TYPE"),
    ("dba_review/V_create_index_no_guard.sql",   "DBA_REVIEW", "CREATE INDEX without IF NOT EXISTS"),
    ("dba_review/V_drop_column.sql",             "DBA_REVIEW", "DROP COLUMN"),
    ("dba_review/V_alter_sequence.sql",          "DBA_REVIEW", "ALTER SEQUENCE non-OWNED"),
    ("dba_review/V_missing_audit_columns.sql",   "DBA_REVIEW", "CREATE TABLE missing audit columns"),

    # Clean cases — AI must NOT flag these
    ("clean/V_guarded_migration.sql",            "CLEAN", "All guards present + audit columns"),
    ("clean/R__fn_refresh_order_summary.sql",    "CLEAN", "TRUNCATE/DELETE inside function body is OK"),
]


def load_fixture(relative_path: str) -> tuple[str, str]:
    """Returns (sql_content, file_name)."""
    fixture = FIXTURES / relative_path
    if not fixture.exists():
        pytest.fail(f"Fixture not found: {fixture}")
    return fixture.read_text(encoding="utf-8"), fixture.name


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def require_token():
    """Skip all tests if GITHUB_TOKEN is not set."""
    if not GITHUB_TOKEN:
        pytest.skip(
            "GITHUB_TOKEN not set — skipping AI eval tests.\n"
            "Set GITHUB_TOKEN to run: export GITHUB_TOKEN=<token>"
        )


@pytest.mark.slow
@pytest.mark.parametrize("fixture_path,expected_tier,description", TEST_CASES)
def test_ai_reviewer_tier(fixture_path: str, expected_tier: str, description: str):
    """
    Evaluates that the AI reviewer returns the correct tier for known SQL patterns.

    Each test is a single API call to GitHub Models with a SQL fixture file.
    The assertion is deterministic: well-known SQL antipatterns should always map
    to a predictable tier.
    """
    sql_content, file_name = load_fixture(fixture_path)
    review = call_ai_reviewer(sql_content, file_name)

    actual_tier = review.get("overall_tier", "UNKNOWN")
    findings    = review.get("findings", [])
    summary     = review.get("summary", "")

    # Primary assertion: tier must match
    assert actual_tier == expected_tier, (
        f"\nFixture:       {fixture_path}\n"
        f"Description:   {description}\n"
        f"Expected tier: {expected_tier}\n"
        f"Actual tier:   {actual_tier}\n"
        f"AI summary:    {summary}\n"
        f"Findings:      {json.dumps(findings, indent=2)}"
    )

    # For HARD_BLOCK and DBA_REVIEW: must have at least one finding
    if expected_tier in ("HARD_BLOCK", "DBA_REVIEW"):
        assert len(findings) > 0, (
            f"Expected findings for {expected_tier} but got empty findings list.\n"
            f"AI summary: {summary}"
        )

        # Each finding must have required fields
        for finding in findings:
            assert "file" in finding,    f"Finding missing 'file': {finding}"
            assert "pattern" in finding, f"Finding missing 'pattern': {finding}"
            assert "risk" in finding,    f"Finding missing 'risk': {finding}"
            assert "fix" in finding,     f"Finding missing 'fix': {finding}"
            assert "tier" in finding,    f"Finding missing 'tier': {finding}"

    # For CLEAN: findings must be empty
    if expected_tier == "CLEAN":
        assert len(findings) == 0, (
            f"Expected CLEAN (no findings) but got {len(findings)} findings:\n"
            f"{json.dumps(findings, indent=2)}"
        )


# ---------------------------------------------------------------------------
# Extended test: verify AI provides corrected SQL for HARD_BLOCK findings
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_hard_block_includes_fix():
    """
    For HARD_BLOCK findings, the AI must include an actual SQL fix (not just a description).
    This validates the 'fix' field is populated with SQL content.
    """
    sql_content, file_name = load_fixture("hard_block/V_add_column_no_guard.sql")
    review = call_ai_reviewer(sql_content, file_name)

    assert review.get("overall_tier") == "HARD_BLOCK"
    findings = review.get("findings", [])
    assert len(findings) > 0

    for f in findings:
        fix = f.get("fix", "")
        assert len(fix) > 10, f"Fix is too short to be real SQL: '{fix}'"
        # Must contain SQL keywords
        assert any(kw in fix.upper() for kw in ["ALTER", "CREATE", "DROP", "INSERT", "UPDATE"]), (
            f"Fix doesn't look like SQL: '{fix}'"
        )
        # Specifically for ADD COLUMN: must include IF NOT EXISTS
        if "ADD COLUMN" in f.get("pattern", "").upper():
            assert "IF NOT EXISTS" in fix.upper(), (
                f"Fix for ADD COLUMN must include IF NOT EXISTS.\nFix: {fix}"
            )


@pytest.mark.slow
def test_function_body_not_flagged():
    """
    Verifies the AI understands dollar-quoting context:
    TRUNCATE and DELETE inside a PL/pgSQL function body in R__*.sql must NOT be flagged.
    This is the most common false positive in naive static analysis.
    """
    sql_content, file_name = load_fixture("clean/R__fn_refresh_order_summary.sql")
    review = call_ai_reviewer(sql_content, file_name)

    tier     = review.get("overall_tier", "UNKNOWN")
    findings = review.get("findings", [])

    # Must not be blocked
    assert tier == "CLEAN", (
        f"R__ function body with TRUNCATE/DELETE was incorrectly flagged as {tier}.\n"
        f"Findings: {json.dumps(findings, indent=2)}\n"
        "This is a false positive — TRUNCATE/DELETE inside a function body is legitimate ETL."
    )
