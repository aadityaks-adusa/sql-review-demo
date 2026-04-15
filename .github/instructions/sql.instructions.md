---
applyTo: "**/*.sql"
---

When reviewing any `.sql` file in this repository:

1. **Determine the file type first** from the filename and path:
   - `V*.sql` → versioned DDL (Flyway runs once, never re-runs)
   - `R__*.sql` → repeatable DDL (re-runs on every change — functions, procedures)
   - `DM*.sql` or file in a `*_dml/` folder → DML only (INSERT/UPDATE/DELETE)

2. **Apply the full SQL review rules** from `.github/copilot-instructions.md`

3. **Context-aware checking:**
   - Statements inside `$$ ... $$` or `$function$ ... $function$` dollar-quote blocks are inside
     a function/procedure body — apply different rules (TRUNCATE, DELETE, UPDATE without WHERE
     are acceptable inside function bodies in R__*.sql)
   - Multi-line statements: always check the full statement before flagging missing WHERE clauses

4. **Format every issue as:**
   - **[HARD_BLOCK]** or **[DBA_REVIEW]** prefix
   - Line reference
   - Risk in plain English (1-2 sentences)
   - Corrected SQL in a fenced code block

5. **Never suggest `CREATE INDEX CONCURRENTLY`** — Flyway transactions forbid it

6. **For new CREATE TABLE**, always check for the 4 audit columns:
   `audt_cr_dt_tm`, `audt_cr_id`, `audt_upd_dt_tm`, `audt_upd_id`
