# sql-review-demo

**Live demo** of the **Detect → Reason → Enforce** SQL PR review gate.

Every pull request that touches a `.sql` file automatically runs three steps:

| Step | Script | What it does |
|---|---|---|
| 1 — Detect | `sql_pr_scan.py` | Runs 25 deterministic regex rules against the diff → `findings.json` |
| 2 — Reason | `llm_reason.py` | Sends findings + diff to GitHub Models (GPT-4o-mini) → `review.json` with plain-English explanation + corrected SQL |
| 3 — Enforce | `enforce.py` | Reads `review.json` → posts PR review, adds label, exits 1 on HARD_BLOCK |

---

## How to see the demo

The `demo/bad-migration` branch is pre-loaded with a SQL file that intentionally triggers two findings.
Open a pull request from that branch to `main` and watch the workflow run.

**Expected outcome:**
- `sql-review / sql-review` check **FAILS** (🚫 HARD_BLOCK)
- Label `sql-hard-block` is added
- The bot posts a `REQUEST_CHANGES` review with LLM-generated explanation and corrected SQL

---

## File types and rules

| File pattern | Type | Rules applied |
|---|---|---|
| `V*.sql` | Versioned DDL (runs once) | ADD COLUMN without IF NOT EXISTS, DROP TABLE without guard, TRUNCATE, missing audit columns |
| `R__*.sql` | Repeatable DDL (re-runs on change) | TRUNCATE outside function body, DROP CASCADE |
| `DM*.sql` / `*_dml/` | DML only | DDL forbidden, naming convention, bulk INSERT limit |

---

## Three-tier classification

| Tier | Enforcement |
|---|---|
| 🚫 HARD_BLOCK | Required CI check fails + PR review `REQUEST_CHANGES` — merge blocked |
| ⚠️ DBA_REVIEW | Check passes + `REQUEST_CHANGES` + label `dba-review-required` — DBA must approve |
| ✅ CLEAN | Check passes + PR `APPROVE` + label `sql-scan-clean` |

---

## Architecture

```
PR opened
    │
    ├─ Step 1: sql_pr_scan.py  → findings.json  (regex, deterministic, ~1s)
    │
    ├─ Step 2: llm_reason.py   → review.json    (GitHub Models GPT-4o-mini)
    │            reads findings.json + git diff
    │            outputs: overall_tier, per-finding risk + corrected SQL
    │
    └─ Step 3: enforce.py                       (GitHub REST API)
                 HARD_BLOCK → exit 1 + REQUEST_CHANGES review + label sql-hard-block
                 DBA_REVIEW → REQUEST_CHANGES review + label dba-review-required
                 CLEAN      → APPROVE review + label sql-scan-clean
```

---

## Branch protection setup (to fully enforce blocking)

In repo **Settings → Branches → main → Branch protection rules:**
- ✅ Require status checks to pass: `sql-review / sql-review`
- ✅ Require branches to be up to date before merging
- ✅ Restrict who can dismiss pull request reviews

This means a HARD_BLOCK or DBA_REVIEW cannot be bypassed by simply dismissing the review.
