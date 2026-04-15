---
applyTo: "**/*.sql"
---
<!--
  ╔══════════════════════════════════════════════════════════════════════╗
  ║  SQL REVIEW RULE TABLE — easy to edit, no code required             ║
  ║                                                                      ║
  ║  To ADD a rule:  copy any row, paste at the bottom of the right     ║
  ║                  table, fill in the four fields, commit to main.    ║
  ║  To REMOVE a rule: delete the row.                                  ║
  ║  To CHANGE a rule: edit the cell text.                              ║
  ║                                                                      ║
  ║  Copilot reads this file automatically on every SQL PR review.      ║
  ╚══════════════════════════════════════════════════════════════════════╝
-->

## File type — check this first

| Filename / path pattern | Type | Key constraint |
|---|---|---|
| `V*.sql` | Versioned DDL — runs once | Idempotency guards mandatory (`IF NOT EXISTS`, `IF EXISTS`) |
| `R__*.sql` | Repeatable DDL — re-runs on every change | Dollar-quote bodies exempt from WHERE/TRUNCATE rules |
| `DM*.sql` or path contains `_dml/` | DML only | DDL forbidden; filename must match `DM<x.y.z>__<desc>.sql` |
| Path contains `/prd/` | Production environment | Extra WHERE-clause scrutiny on every DELETE/UPDATE |

---

## ⛔ HARD_BLOCK rules

*Post inline: `[HARD_BLOCK] <risk>` and the corrected SQL. Author must fix before merge.*

| # | SQL pattern to detect | File scope | Risk (one line) | Fix (one line) |
|---|---|---|---|---|
| H1 | `ADD COLUMN` without `IF NOT EXISTS` | `V*.sql` | Flyway retry crashes with "column already exists" — caused OCDOMAIN-15294 (45-min outage) | `ADD COLUMN IF NOT EXISTS` |
| H2 | `DROP TABLE` without `IF EXISTS` | `V*.sql` | Crashes on Flyway retry or fresh-environment deploy | `DROP TABLE IF EXISTS` |
| H3 | `DELETE FROM` without `WHERE` | All | Wipes the entire table; check full multi-line stmt; exempt: dollar-quote bodies in `R__*` | Add a `WHERE` clause |
| H4 | `UPDATE ... SET` without `WHERE` | All | Modifies every row; same multi-line check and dollar-quote exemption as H3 | Add a `WHERE` clause |
| H5 | `TRUNCATE` outside `$$...$$` blocks | `V*.sql` | Destroys all rows with no rollback | Remove, or move into an `R__*` function body |
| H6 | DDL (`ALTER`/`CREATE`/`DROP TABLE`, `CREATE`/`DROP INDEX`) in a `DM*.sql` or `*_dml/` file | DML files | Policy: DML pipelines allow SELECT/INSERT/UPDATE/DELETE only — DDL breaks the pipeline | Move DDL to a `V*.sql` file |
| H7 | DML filename does not match `DM<x.y.z>__<description>.sql` | `DM*.sql` | Flyway skips or errors on malformed filenames | Rename to the correct format |

---

## ⚠️ DBA_REVIEW rules

*Post inline: `⚠️ [DBA_REVIEW] <risk>` and a safer alternative. PR may merge with DBA sign-off.*

| # | SQL pattern to detect | Risk (one line) | Safe alternative |
|---|---|---|---|
| D1 | `ALTER COLUMN ... TYPE` | Full row rewrite + exclusive lock; real revert OCDOMAIN-7659 (NUMERIC↔DOUBLE) | Add new col + backfill + rename |
| D2 | `DROP TABLE` / `DROP COLUMN` / `DROP INDEX` / `DROP VIEW` / `DROP SCHEMA` | Destructive — confirm backup exists and all app consumers are removed | Archive first; drop in a follow-up |
| D3 | `DROP ... CASCADE` | Silently removes ALL dependent objects (FKs, views, indexes) | Run `SELECT * FROM pg_depend` before dropping |
| D4 | `ALTER COLUMN SET NOT NULL` | Full table scan + exclusive lock for its entire duration | `ADD CONSTRAINT c CHECK (col IS NOT NULL) NOT VALID` then `VALIDATE CONSTRAINT` separately |
| D5 | `ADD COLUMN ... NOT NULL` without a `DEFAULT` | Table lock on PG < 11; risky if table has rows on PG 11+ | Add `DEFAULT` first, backfill, then drop default |
| D6 | `ALTER SEQUENCE` with `INCREMENT`/`RESTART`/`CACHE`/`MINVALUE`/`MAXVALUE` | Sequence gap or reset breaks app ID generation — real prod revert V2024_0_15 | Only `OWNED BY` changes are safe without DBA review |
| D7 | `CREATE EXTENSION` | Requires superuser privilege; may not be available in all environments | DBA must pre-create the extension |
| D8 | `RENAME COLUMN` / `RENAME TO` | Breaking rename — all app consumers must update in the same release | Add new column, migrate data, drop old column |
| D9 | `CREATE TABLE` without `IF NOT EXISTS` | Flyway retry fails with "relation already exists" | `CREATE TABLE IF NOT EXISTS` |
| D10 | `CREATE INDEX` without `IF NOT EXISTS` | Flyway retry fails (`CONCURRENTLY` is forbidden inside Flyway transactions — do not suggest it) | `CREATE INDEX IF NOT EXISTS` |
| D11 | New `CREATE TABLE` missing any of: `audt_cr_dt_tm`, `audt_cr_id`, `audt_upd_dt_tm`, `audt_upd_id` | Policy: all application tables must include 4 audit columns with `DEFAULT CURRENT_TIMESTAMP` / `DEFAULT CURRENT_USER` | Add the missing audit columns |
| D12 | Column named: `email`, `ssn`, `credit_card`, `cvv`, `password`, `phone`, `dob`, `account_number` | PII column — privacy/compliance review required | Confirm data is encrypted or masked |
| D13 | `DELETE` or `UPDATE` in a file whose path contains `/prd/` | Production data at risk; a wide WHERE clause can cause mass data loss | Verify WHERE clause covers only the intended rows |

---

## ✅ Never flag these

- `TRUNCATE` / `DELETE` / `UPDATE` without `WHERE` **inside** `$$ ... $$` or `$token$ ... $token$` blocks in `R__*.sql` — legitimate ETL pattern
- `CREATE INDEX` without `CONCURRENTLY` — correct for Flyway (transactions forbid CONCURRENTLY)
- `ALTER SEQUENCE ... OWNED BY` — safe, no issue
- `COMMENT ON` statements — encouraged
- `qrtz_*` tables — third-party Quartz scheduler schema, audit columns are not required

---

## Template — copy to add a new rule

**HARD_BLOCK row** (paste at the bottom of the ⛔ table above):
```
| H8 | `YOUR SQL PATTERN` | V*.sql / R__*.sql / All / DM files | One-line risk | One-line fix |
```

**DBA_REVIEW row** (paste at the bottom of the ⚠️ table above):
```
| D14 | `YOUR SQL PATTERN` | One-line risk | One-line safe alternative |
```
