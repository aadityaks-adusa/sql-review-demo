#!/usr/bin/env python3
"""
SQL PR Scan — Detect Step
Scans changed SQL files and classifies risk into three tiers:
  Tier 1 (HARD_BLOCK)  - auto-fails the PR check
  Tier 2 (DBA_REVIEW)  - passes check but requires DBA approval
  Tier 3 (CLEAN)       - no action needed

Outputs:
  - findings.json  (for llm_reason.py)
  - GitHub Actions step summary
  - Exit code 0 always — enforce.py is responsible for blocking
"""

import os
import re
import sys
import json
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Tier(Enum):
    CLEAN = 1
    DBA_REVIEW = 2
    HARD_BLOCK = 3


@dataclass
class Finding:
    file: str
    line_number: int
    line_content: str
    pattern: str
    description: str
    tier: Tier


@dataclass
class FileResult:
    path: str
    file_type: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def tier(self) -> Tier:
        if not self.findings:
            return Tier.CLEAN
        return max((f.tier for f in self.findings), key=lambda t: t.value)


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

TIER1_DML_ONLY = [
    (r"(?i)\bALTER\s+TABLE\b",    "ALTER TABLE in DML file",    "DDL is forbidden inside _dml files"),
    (r"(?i)\bCREATE\s+TABLE\b",   "CREATE TABLE in DML file",   "DDL is forbidden inside _dml files"),
    (r"(?i)\bDROP\s+TABLE\b",     "DROP TABLE in DML file",     "DDL is forbidden inside _dml files"),
    (r"(?i)\bCREATE\s+INDEX\b",   "CREATE INDEX in DML file",   "DDL is forbidden inside _dml files"),
    (r"(?i)\bDROP\s+INDEX\b",     "DROP INDEX in DML file",     "DDL is forbidden inside _dml files"),
    (r"(?i)\bDROP\s+COLUMN\b",    "DROP COLUMN in DML file",    "DDL is forbidden inside _dml files"),
    (r"(?i)\bCREATE\s+SEQUENCE\b","CREATE SEQUENCE in DML file","DDL is forbidden inside _dml files"),
    (r"(?i)\bDROP\s+SEQUENCE\b",  "DROP SEQUENCE in DML file",  "DDL is forbidden inside _dml files"),
    (r"(?i)\bCREATE\s+VIEW\b",    "CREATE VIEW in DML file",    "DDL is forbidden inside _dml files"),
]

TIER2_DDL = [
    (r"(?i)\bDROP\s+TABLE\b",            "DROP TABLE",            "Destructive — DBA must confirm no active consumers"),
    (r"(?i)\bDROP\s+COLUMN\b",           "DROP COLUMN",           "Data loss — DBA must confirm column unused across all app code"),
    (r"(?i)\bDROP\s+INDEX\b",            "DROP INDEX",            "Performance impact — DBA must check query plans"),
    (r"(?i)\bDROP\s+VIEW\b",             "DROP VIEW",             "Breaking change — DBA must confirm no apps consume this view"),
    (r"(?i)\bDROP\s+SCHEMA\b",           "DROP SCHEMA",           "Catastrophic — removes ALL objects in schema"),
    (r"(?i)\bDROP\s+SEQUENCE\b",         "DROP SEQUENCE",         "Breaks auto-increment — DBA must confirm sequence not referenced"),
    (r"(?i)\bALTER\s+COLUMN\b.{0,100}\bTYPE\b", "ALTER COLUMN TYPE", "Type change rewrites all rows — DBA must verify cast safety"),
    (r"(?i)\bRENAME\s+COLUMN\b",         "RENAME COLUMN",         "Breaking rename — app code must be updated atomically"),
    (r"(?i)\bRENAME\s+TO\b",             "RENAME TABLE/INDEX",    "Breaking rename — DBA must confirm no dependents"),
    (r"(?i)\bDROP\s+CONSTRAINT\b",       "DROP CONSTRAINT",       "Removes data integrity — DBA must confirm app-level validation exists"),
    (r"(?i)\bCREATE\s+(?:UNIQUE\s+)?INDEX\b(?!\s+IF\s+NOT\s+EXISTS)(?!\s+CONCURRENTLY)",
     "CREATE INDEX without IF NOT EXISTS",
     "Missing guard — index creation fails on Flyway retry"),
    (r"(?i)\bCREATE\s+INDEX\s+CONCURRENTLY\b",
     "CREATE INDEX CONCURRENTLY",
     "CONCURRENTLY cannot run inside a Flyway transaction — remove it"),
    (r"(?i)\bCREATE\s+TABLE\b(?!\s+IF\s+NOT\s+EXISTS)(?!\s*\w+\s*(?:AS\s+(?:TABLE|SELECT)|LIKE\s))",
     "CREATE TABLE without IF NOT EXISTS",
     "Missing guard — table creation fails on Flyway retry"),
    (r"(?i)\bALTER\s+SEQUENCE\b(?!.{0,120}\bOWNED\s+BY\b)",
     "ALTER SEQUENCE (value change)",
     "Sequence value changes have caused real production reverts — DBA must review"),
    (r"(?i)\bCREATE\s+EXTENSION\b",
     "CREATE EXTENSION",
     "Requires superuser privilege — DBA must confirm it's approved in all environments"),
]

AUDIT_CR_PATTERN    = re.compile(r"(?i)\baudt_cr_dt_tm\b|\bcreated_at\b")
AUDIT_UPD_PATTERN   = re.compile(r"(?i)\baudt_upd_dt_tm\b|\bupdated_at\b")
AUDIT_EXEMPT_PATTERN = re.compile(r"(?i)(qrtz_|flyway_schema_history|_migration\b|_backup\b|AS\s+(?:TABLE|SELECT))")

TIER2_DML_PROD = [
    (r"(?i)\bDELETE\s+FROM\b", "DELETE (production path)", "All prod DML DELETEs require DBA review of WHERE scope"),
    (r"(?i)\bUPDATE\b.*\bSET\b","UPDATE (production path)", "All prod DML UPDATEs require DBA review of WHERE scope"),
]

PII_PATTERNS = [
    r"\b(email|ssn|credit_card|card_number|cvv|password|phone|address|dob|date_of_birth|full_name|account_number)\b",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_dml_file(path: str) -> bool:
    p = Path(path)
    return any(part.endswith("_dml") for part in p.parts) or p.name.startswith("DM")

def is_versioned_ddl(path: str) -> bool:
    p = Path(path)
    return p.name.startswith("V") and p.name.endswith(".sql") and not is_dml_file(path)

def is_repeatable_ddl(path: str) -> bool:
    p = Path(path)
    return p.name.startswith("R__") and p.name.endswith(".sql") and not is_dml_file(path)

def is_prod_path(path: str) -> bool:
    return "prd" in Path(path).parts

def strip_comments(line: str) -> str:
    return re.sub(r"--.*$", "", line)

def get_changed_sql_files() -> list[str]:
    base = os.environ.get("BASE_SHA", "origin/main")
    head = os.environ.get("HEAD_SHA", "HEAD")
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base, head],
            capture_output=True, text=True, check=True,
        )
        return [f.strip() for f in result.stdout.splitlines() if f.strip().endswith(".sql")]
    except subprocess.CalledProcessError as e:
        print(f"git diff failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)

def get_added_lines(path: str) -> list[tuple[int, str]]:
    base = os.environ.get("BASE_SHA", "origin/main")
    head = os.environ.get("HEAD_SHA", "HEAD")
    try:
        result = subprocess.run(
            ["git", "diff", base, head, "--unified=0", "--", path],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return [(i + 1, line.rstrip()) for i, line in enumerate(f.readlines())]
        except OSError:
            return []

    added, current_line = [], 0
    for raw in result.stdout.splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if m:
            current_line = int(m.group(1))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            added.append((current_line, raw[1:]))
            current_line += 1
        elif not raw.startswith("-"):
            current_line += 1
    return added

def is_inside_function_body(added_lines: list[tuple[int, str]], line_no: int) -> bool:
    _DOLLAR_TAG = re.compile(r"\$([a-zA-Z0-9_]*)\$")
    pre_text = "\n".join(c for ln, c in added_lines if ln < line_no)
    tag_counts: dict[str, int] = {}
    for m in _DOLLAR_TAG.finditer(pre_text):
        tag = m.group(0)
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
    for tag, count in tag_counts.items():
        if count % 2 == 1 and re.search(r"(?i)\b(?:AS|DO)\s+" + re.escape(tag), pre_text):
            return True
    return False

def _extract_statement_at(added_lines: list[tuple[int, str]], target_line: int) -> Optional[str]:
    in_stmt, stmt_lines = False, []
    for ln, content in added_lines:
        if ln == target_line:
            in_stmt = True
        if in_stmt:
            stmt_lines.append(content)
            if content.strip().endswith(";"):
                break
    return "\n".join(stmt_lines) if stmt_lines else None

def count_value_rows(added_lines: list[tuple[int, str]]) -> int:
    content = "\n".join(line for _, line in added_lines)
    return len(re.findall(r"\((?:[^()]+)\)", content))

def check_naming_convention(path: str, is_dml: bool) -> Optional[Finding]:
    if not is_dml:
        return None
    name = Path(path).name
    if not re.match(r"^DM\d+\.\d+\.\d+__.+\.sql$", name):
        return Finding(
            path, 0, name,
            "Naming convention violation",
            f"DML file must be DM<x.y.z>__<description>.sql (got: {name})",
            Tier.HARD_BLOCK,
        )
    return None


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

def scan_file(path: str) -> FileResult:  # noqa: C901
    dml       = is_dml_file(path)
    versioned = is_versioned_ddl(path)
    repeatable= is_repeatable_ddl(path)
    ddl       = versioned or repeatable

    file_type = "DML" if dml else ("DDL_versioned" if versioned else ("DDL_repeatable" if repeatable else "OTHER"))
    result    = FileResult(path=path, file_type=file_type)
    added_lines = get_added_lines(path)
    if not added_lines:
        return result

    added_content = "\n".join(c for _, c in added_lines)

    for line_no, raw_line in added_lines:
        line    = strip_comments(raw_line)
        stripped = line.strip()
        if not stripped:
            continue

        has_override = bool(re.search(r"(?i)--\s*REVIEWED\s*:", raw_line))
        inside_fn    = repeatable and is_inside_function_body(added_lines, line_no)

        # TRUNCATE
        if re.search(r"(?i)\bTRUNCATE\b", stripped):
            if not re.search(r"(?i)\bGRANT\b", stripped) and not stripped.startswith("--"):
                if dml:
                    result.findings.append(Finding(path, line_no, raw_line.strip(), "TRUNCATE in DML file", "TRUNCATE is DDL — forbidden in _dml files", Tier.HARD_BLOCK))
                elif versioned:
                    result.findings.append(Finding(path, line_no, raw_line.strip(), "TRUNCATE TABLE", "TRUNCATE in a versioned migration destroys all rows irreversibly", Tier.HARD_BLOCK))
                elif repeatable and not inside_fn:
                    result.findings.append(Finding(path, line_no, raw_line.strip(), "TRUNCATE (top-level R__)", "TRUNCATE at top level of repeatable — verify ETL intent", Tier.DBA_REVIEW))

        # DELETE without WHERE
        if re.search(r"(?i)\bDELETE\s+FROM\b", stripped):
            if not stripped.startswith("--") and not re.search(r"(?i)\bGRANT\b", stripped):
                if not (repeatable and inside_fn):
                    stmt = _extract_statement_at(added_lines, line_no)
                    if stmt and not re.search(r"(?i)\bWHERE\b", stmt):
                        result.findings.append(Finding(path, line_no, raw_line.strip(), "DELETE without WHERE", "Unfiltered full-table delete — will wipe every row", Tier.HARD_BLOCK))

        # UPDATE without WHERE
        if re.search(r"(?i)\bUPDATE\s+[\w\".]+\s+SET\b", stripped):
            if not stripped.startswith("--") and not (repeatable and inside_fn):
                stmt = _extract_statement_at(added_lines, line_no)
                if stmt and not re.search(r"(?i)\bWHERE\b", stmt):
                    result.findings.append(Finding(path, line_no, raw_line.strip(), "UPDATE without WHERE", "Unfiltered update modifies every row in the table", Tier.HARD_BLOCK))

        # ADD COLUMN without IF NOT EXISTS (versioned only)
        if versioned and re.search(r"(?i)\bADD\s+COLUMN\b", stripped) and not stripped.startswith("--"):
            if not re.search(r"(?i)\bIF\s+NOT\s+EXISTS\b", stripped):
                result.findings.append(Finding(
                    path, line_no, raw_line.strip(),
                    "ADD COLUMN without IF NOT EXISTS",
                    "Flyway will fail on retry — real incident OCDOMAIN-15294 was caused by this. Use: ALTER TABLE IF EXISTS <t> ADD COLUMN IF NOT EXISTS <col>",
                    Tier.HARD_BLOCK,
                ))

        # DROP TABLE without IF EXISTS (versioned only)
        if versioned and re.search(r"(?i)\bDROP\s+TABLE\b", stripped) and not stripped.startswith("--"):
            if not re.search(r"(?i)\bIF\s+EXISTS\b", stripped):
                result.findings.append(Finding(path, line_no, raw_line.strip(), "DROP TABLE without IF EXISTS", "Flyway retry will fail if table doesn't exist", Tier.HARD_BLOCK))

        # DDL in DML
        if dml and not stripped.startswith("--"):
            for pattern, name, desc in TIER1_DML_ONLY:
                if re.search(pattern, stripped):
                    if not any(f.line_number == line_no and f.pattern == name for f in result.findings):
                        result.findings.append(Finding(path, line_no, raw_line.strip(), name, desc, Tier.HARD_BLOCK))

        # Tier 2 DDL risks
        if ddl and not dml and not stripped.startswith("--"):
            for pattern, name, desc in TIER2_DDL:
                if re.search(pattern, stripped):
                    if not any(f.line_number == line_no and f.tier == Tier.HARD_BLOCK for f in result.findings):
                        if not any(f.line_number == line_no and f.pattern == name for f in result.findings):
                            result.findings.append(Finding(path, line_no, raw_line.strip(), name, desc, Tier.DBA_REVIEW))

        # ALTER COLUMN SET NOT NULL
        if ddl and not stripped.startswith("--") and re.search(r"(?i)\bSET\s+NOT\s+NULL\b", stripped):
            if not any(f.line_number == line_no and "SET NOT NULL" in f.pattern for f in result.findings):
                result.findings.append(Finding(path, line_no, raw_line.strip(), "ALTER COLUMN SET NOT NULL",
                    "Full table scan + exclusive lock for duration — DBA must confirm no existing NULLs and acceptable table size", Tier.DBA_REVIEW))

        # DROP CASCADE
        if ddl and not stripped.startswith("--") and re.search(r"(?i)\bDROP\b", stripped) and re.search(r"(?i)\bCASCADE\b", stripped):
            if not any(f.line_number == line_no and "CASCADE" in f.pattern for f in result.findings):
                result.findings.append(Finding(path, line_no, raw_line.strip(), "DROP CASCADE",
                    "Silently removes ALL dependent objects — DBA must enumerate dependents first", Tier.DBA_REVIEW))

        # Prod path DML
        if dml and is_prod_path(path) and not stripped.startswith("--"):
            for pattern, name, desc in TIER2_DML_PROD:
                if re.search(pattern, stripped):
                    if not any(f.line_number == line_no and f.pattern == name for f in result.findings):
                        result.findings.append(Finding(path, line_no, raw_line.strip(), name, desc, Tier.DBA_REVIEW))

        # PII columns
        if not stripped.startswith("--"):
            for pii_pat in PII_PATTERNS:
                if re.search(pii_pat, stripped, re.IGNORECASE):
                    if not any(f.line_number == line_no and "PII" in f.pattern for f in result.findings):
                        col = re.search(pii_pat, stripped, re.IGNORECASE).group(0)
                        result.findings.append(Finding(path, line_no, raw_line.strip(), f"PII column: {col}",
                            f"PII-adjacent column '{col}' — privacy compliance review required", Tier.DBA_REVIEW))

    # Whole-file: audit columns
    if versioned:
        _check_audit_columns(path, added_content, result)

    # Whole-file: bulk INSERT
    if dml:
        rc = count_value_rows(added_lines)
        if rc > 50:
            result.findings.append(Finding(path, 0, f"~{rc} value tuples", "Bulk INSERT (>50 rows)",
                "DML pipeline is not for bulk loads — DBA must review volume", Tier.DBA_REVIEW))

    # Naming convention
    naming = check_naming_convention(path, dml)
    if naming:
        result.findings.append(naming)

    return result


def _check_audit_columns(path: str, added_content: str, result: FileResult) -> None:
    blocks = re.findall(r"(?i)(CREATE\s+TABLE\b.*?\))\s*;", added_content, re.DOTALL)
    for block in blocks:
        if AUDIT_EXEMPT_PATTERN.search(block):
            continue
        has_cr  = bool(AUDIT_CR_PATTERN.search(block))
        has_upd = bool(AUDIT_UPD_PATTERN.search(block))
        if not has_cr or not has_upd:
            m = re.search(r"(?i)CREATE\s+TABLE\b(?:\s+IF\s+NOT\s+EXISTS)?\s+(\S+)", block)
            tname = m.group(1) if m else "(unknown)"
            missing = []
            if not has_cr:  missing.append("audt_cr_dt_tm")
            if not has_upd: missing.append("audt_upd_dt_tm")
            result.findings.append(Finding(path, 0, f"CREATE TABLE {tname}", "Missing audit columns",
                f"Table {tname} is missing required audit columns: {', '.join(missing)}. "
                "All new application tables must include audt_cr_dt_tm, audt_cr_id, audt_upd_dt_tm, audt_upd_id.",
                Tier.DBA_REVIEW))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _write_findings_json(results: list[FileResult]) -> None:
    findings_path = os.environ.get("SQL_SCAN_FINDINGS_FILE")
    findings = [
        {
            "file": f.file,
            "file_type": r.file_type,
            "line_number": f.line_number,
            "line_content": f.line_content,
            "pattern": f.pattern,
            "description": f.description,
            "tier": f.tier.name,
        }
        for r in results
        for f in r.findings
    ]
    if findings_path:
        with open(findings_path, "w", encoding="utf-8") as fp:
            json.dump(findings, fp, indent=2)
        print(f"findings.json: {len(findings)} finding(s) → {findings_path}")
    else:
        print(json.dumps(findings, indent=2))


def _write_step_summary(text: str):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def build_summary(results: list[FileResult]) -> str:
    overall = max((r.tier for r in results), key=lambda t: t.value, default=Tier.CLEAN)
    icon = {"CLEAN": "✅", "DBA_REVIEW": "⚠️", "HARD_BLOCK": "🚫"}[overall.name]
    lines = [f"## {icon} SQL Scan — {overall.name.replace('_',' ')}\n"]
    lines.append("| File | Type | Tier | Findings |")
    lines.append("|------|------|------|----------|")
    for r in results:
        t = {"CLEAN": "✅", "DBA_REVIEW": "⚠️", "HARD_BLOCK": "🚫"}[r.tier.name]
        lines.append(f"| `{r.path}` | {r.file_type} | {t} {r.tier.name} | {len(r.findings) or '—'} |")
    return "\n".join(lines)


def main():
    sql_files = get_changed_sql_files()

    if not sql_files:
        print("No SQL files changed.")
        _write_findings_json([])
        _write_step_summary("## ✅ SQL Scan — CLEAN\n\nNo SQL files changed.")
        sys.exit(0)

    results = [scan_file(f) for f in sql_files]
    _write_findings_json(results)
    _write_step_summary(build_summary(results))
    print(build_summary(results))
    # Note: do NOT exit 1 here — enforce.py handles blocking after LLM reasoning


if __name__ == "__main__":
    main()
