# SQL PR Review Instructions — PostgreSQL + Flyway
# Coreservices Database Deployments

When reviewing SQL migration files, apply the rules below. Classify every issue as
HARD_BLOCK (must fix before merge) or DBA_REVIEW (needs DBA sign-off).

## Repo context
- Flyway runs all SQL inside a transaction — if it fails, it retries the whole script
- V*.sql = versioned DDL (runs once), R__*.sql = repeatable DDL, DM*.sql or *_dml/ = DML only
- /prd/ path = production environment

## HARD_BLOCK — must fix before merge

1. **ADD COLUMN without IF NOT EXISTS** in V*.sql — retry crashes with "column already exists"
   Fix: `ALTER TABLE IF EXISTS <schema>.<table> ADD COLUMN IF NOT EXISTS <col> <type>`
   Real incident: OCDOMAIN-15294 (PR #573)

2. **DROP TABLE without IF EXISTS** in V*.sql — fails on retry or fresh-env deploy

3. **DELETE FROM without WHERE** — check across multiple lines; exclude function bodies in R__*

4. **UPDATE ... SET without WHERE** — same multi-line check; exclude function bodies in R__*

5. **TRUNCATE in V*.sql** — destroys all rows with no rollback
   Exception: TRUNCATE inside a function/procedure body in R__*.sql is fine (ETL pattern)

6. **DDL inside a DML file** (_dml/ folder or DM*.sql):
   Forbidden: ALTER TABLE, CREATE TABLE, DROP TABLE, CREATE/DROP INDEX, CREATE/DROP SEQUENCE, CREATE VIEW, TRUNCATE

7. **Wrong DML filename** — must match DM<x.y.z>__<description>.sql exactly

## DBA_REVIEW — requires DBA approval

8. **ALTER COLUMN ... TYPE** — rewrites every row, exclusive lock; check for USING clause
   Real revert: OCDOMAIN-7659 (NUMERIC↔DOUBLE PRECISION)

9. **DROP TABLE / DROP COLUMN / DROP INDEX / DROP VIEW / DROP SCHEMA** — destructive; confirm backup + no consumers

10. **DROP ... CASCADE** — silently removes ALL dependent objects; run pg_depend check first

11. **ALTER COLUMN SET NOT NULL** — full table scan, exclusive lock
    Safer: ADD CONSTRAINT ... CHECK (col IS NOT NULL) NOT VALID, then VALIDATE CONSTRAINT

12. **ADD COLUMN ... NOT NULL without DEFAULT** — locks table on PG < 11; risky on PG 11+ with rows

13. **ALTER SEQUENCE** (non-OWNED BY) — INCREMENT/RESTART/CACHE changes break apps
    Real revert: V2024_0_15__cart_item_seq_increment

14. **CREATE EXTENSION** — requires superuser privilege

15. **RENAME COLUMN / RENAME TO** — breaking rename; app code must change atomically

16. **CREATE TABLE without IF NOT EXISTS** — fails on Flyway retry

17. **CREATE INDEX without IF NOT EXISTS** — fails on retry
    Never suggest CONCURRENTLY — Flyway transactions forbid it

18. **New CREATE TABLE missing audit columns**:
    Required: audt_cr_dt_tm, audt_cr_id, audt_upd_dt_tm, audt_upd_id (all with DEFAULT CURRENT_TIMESTAMP / CURRENT_USER)
    Exempt: qrtz_*, flyway_*, *_migration, *_backup, CREATE TABLE AS SELECT

19. **PII column names**: email, ssn, credit_card, card_number, cvv, password, phone, address, dob, date_of_birth, full_name, account_number

20. **DELETE or UPDATE in /prd/ DML files** — verify WHERE clause scope

## Do NOT flag
- TRUNCATE / DELETE / UPDATE inside function bodies in R__*.sql
- CREATE INDEX without CONCURRENTLY (correct for Flyway)
- ALTER SEQUENCE ... OWNED BY only
- COMMENT ON statements
- qrtz_* tables (no audit column requirement)

## For each issue, provide
1. Tier (HARD_BLOCK or DBA_REVIEW)
2. Specific line reference
3. Why it's risky (1-2 sentences)
4. The exact corrected SQL
