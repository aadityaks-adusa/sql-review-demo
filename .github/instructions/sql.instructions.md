---
applyTo: "**/*.sql"
---
<!--
  ╔══════════════════════════════════════════════════════════════════════════╗
  ║  SQL REVIEW RULE TABLE — easy to edit, no code or regex required        ║
  ║                                                                          ║
  ║  To ADD a rule:    copy the template row at the bottom, paste it into   ║
  ║                    the right table below, fill in the four cells,        ║
  ║                    commit to main. Copilot picks it up automatically.    ║
  ║  To REMOVE a rule: delete its row.                                       ║
  ║  To CHANGE a rule: edit the cell text — plain English, no code.         ║
  ║                                                                          ║
  ║  This file is read by:                                                   ║
  ║    • GitHub Copilot code review (automatically, on every SQL PR)         ║
  ║    • .github/scripts/sql_review_prompt.md references these rules         ║
  ╚══════════════════════════════════════════════════════════════════════════╝
-->

## Step 1 — File type (check this before any rule)

| Filename / path pattern | Type | Key constraint |
|---|---|---|
| `V*.sql` | Versioned DDL — **runs once** | All structural changes need idempotency guards (`IF NOT EXISTS`, `IF EXISTS`) |
| `R__*.sql` | Repeatable DDL — **re-runs on every file change** | Dollar-quote bodies (`$$...$$`) are function/proc bodies — TRUNCATE/DELETE/UPDATE inside them are **legitimate ETL, do not flag** |
| `DM*.sql` or path contains `_dml/` | DML only | DDL is **forbidden** here; filename must be `DM<x.y.z>__<desc>.sql` |
| Path contains `/prd/` AND is DML | Production DML | Extra scrutiny on every DELETE/UPDATE WHERE clause |

---

## ⛔ HARD_BLOCK rules — post inline `[HARD_BLOCK]` comment; author must fix before merge

| Rule | SQL pattern to detect | File scope | Risk (one sentence) | Correct fix |
|---|---|---|---|---|
| H1 | `ADD COLUMN <name>` without `IF NOT EXISTS` | `V*.sql` | Flyway retry crashes "column already exists" — caused OCDOMAIN-15294 (45-min production outage) | `ALTER TABLE IF EXISTS <schema>.<table> ADD COLUMN IF NOT EXISTS <col> <type>;` |
| H2 | `DROP TABLE` without `IF EXISTS` | `V*.sql` | Crashes on Flyway retry or fresh-environment deploy | `DROP TABLE IF EXISTS <schema>.<table>;` |
| H3 | `DELETE FROM <table>` with no `WHERE` in the full statement | All (except dollar-quote bodies in `R__*`) | Wipes the entire table with no rollback — check multi-line; a WHERE on the next line is fine | Add a specific `WHERE` clause |
| H4 | `UPDATE <table> SET ...` with no `WHERE` in the full statement | All (except dollar-quote bodies in `R__*`) | Modifies every row in the table — same multi-line check as H3 | Add a specific `WHERE` clause |
| H5 | `TRUNCATE TABLE` not inside a `$$...$$` block | `V*.sql` | Destroys all rows with no rollback in a one-time migration | Remove, or move into an `R__*` function body |
| H6 | DDL (`ALTER TABLE`, `CREATE TABLE`, `DROP TABLE`, `CREATE INDEX`, `DROP INDEX`, `CREATE SEQUENCE`, `CREATE VIEW`) | `DM*.sql` or `*_dml/` folder | Violates Confluence DML CICD policy — DDL is forbidden in DML pipeline context | Move DDL to a `V*.sql` versioned migration |
| H7 | Filename does not match `DM<x.y.z>__<description>.sql` | `DM*.sql` or `*_dml/` folder | Flyway may skip or error on malformed DML filename | Rename to `DM<next_version>__<description>.sql` |

---

## ⚠️ DBA_REVIEW rules — post inline `⚠️ [DBA_REVIEW]` comment; DBA must approve before merge

| Rule | SQL pattern to detect | Risk (one sentence) | Safe alternative |
|---|---|---|---|
| D1 | `ALTER COLUMN <name> TYPE <new_type>` | Full row rewrite + exclusive lock — real prod revert OCDOMAIN-7659 (NUMERIC↔DOUBLE) | Add new col + backfill + rename; always verify USING cast clause |
| D2 | `DROP TABLE` / `DROP COLUMN` / `DROP INDEX` / `DROP VIEW` / `DROP SCHEMA` | Destructive — `DROP SCHEMA` removes ALL objects | Confirm backup exists and no app consumers remain; archive first |
| D3 | `DROP ... CASCADE` | Silently removes ALL dependent objects (FKs, views, indexes) | Run `SELECT * FROM pg_depend` first; drop dependents explicitly |
| D4 | `ALTER COLUMN <name> SET NOT NULL` (standalone) | Full table scan + exclusive lock for its entire duration | `ADD CONSTRAINT c CHECK (col IS NOT NULL) NOT VALID` then `VALIDATE CONSTRAINT c` separately |
| D5 | `ADD COLUMN <name> <type> NOT NULL` without a `DEFAULT` | Table lock on PG < 11; risky on PG 11+ if rows exist | Add `DEFAULT <value>` first, backfill, then drop default in a follow-up migration |
| D6 | `ALTER SEQUENCE` with `INCREMENT BY` / `RESTART` / `CACHE` / `MINVALUE` / `MAXVALUE` (not `OWNED BY`) | Sequence reset/gap breaks app ID generation — real prod revert V2024_0_15 (cart seq) | Only `OWNED BY` changes are safe without DBA review |
| D7 | `CREATE EXTENSION <name>` | Requires superuser or `pg_extension_owner` privilege — may fail in nonprd/prd differently | DBA must pre-create extension in all target environments |
| D8 | `RENAME COLUMN <old> TO <new>` or `ALTER TABLE ... RENAME TO` | Breaking rename — all consumers must update atomically in the same release | Add new col + backfill + drop old col (Blue-Green rename) |
| D9 | `CREATE TABLE <name>` without `IF NOT EXISTS` | Flyway retry fails "relation already exists" | `CREATE TABLE IF NOT EXISTS <schema>.<table> (...);` |
| D10 | `CREATE INDEX <name>` without `IF NOT EXISTS` | Flyway retry fails — **never suggest CONCURRENTLY** (Flyway transactions forbid it) | `CREATE INDEX IF NOT EXISTS <name> ON <table>(<col>);` |
| D11 | New `CREATE TABLE` missing any of: `audt_cr_dt_tm`, `audt_cr_id`, `audt_upd_dt_tm`, `audt_upd_id` | Policy: all app tables must have 4 audit columns with `DEFAULT CURRENT_TIMESTAMP / CURRENT_USER` | Add the missing columns before the closing parenthesis |
| D12 | Column named: `email`, `ssn`, `credit_card`, `cvv`, `password`, `phone`, `dob`, `account_number`, `full_name`, `card_number` | PII / sensitive data — privacy and compliance review required | Confirm data is encrypted at rest and masked in logs |
| D13 | `DELETE FROM` or `UPDATE ... SET` in a file whose path contains `/prd/` | Production data at risk even with a WHERE clause | DBA must verify WHERE clause covers only the intended rows |

---

## ✅ Never flag these

- `TRUNCATE` / `DELETE` / `UPDATE` without `WHERE` **inside** `$$...$$` or `$token$...$token$` in `R__*.sql` — ETL pattern
- `CREATE INDEX` without `CONCURRENTLY` — correct for Flyway (transactions forbid CONCURRENTLY)
- `ALTER SEQUENCE ... OWNED BY` only — safe ownership change
- `COMMENT ON` statements — fine, encouraged
- `qrtz_*` tables — third-party Quartz scheduler; no audit column requirement
- `flyway_schema_history` — internal Flyway table; never touch

---

## Template — copy to add a new rule

**HARD_BLOCK row** (paste at the bottom of the ⛔ table):
```
| H8 | `YOUR PATTERN` | V*.sql / R__*.sql / All / DM files | One-sentence risk | One-line fix |
```

**DBA_REVIEW row** (paste at the bottom of the ⚠️ table):
```
| D14 | `YOUR PATTERN` | One-sentence risk | Safe alternative |
```
