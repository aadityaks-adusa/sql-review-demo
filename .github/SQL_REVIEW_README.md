# Copilot SQL Review Gate

Automated SQL pull-request review pipeline. **GitHub Copilot is the sole reviewer.**
GitHub Actions only reads Copilot's verdict, applies a tier label, and posts a
required status check that gates merge.

No comments are posted by `github-actions[bot]`. No GitHub Models / GPT-4o calls.
No hardcoded regex rules — rules live in plain markdown.

---

## Architecture

```
PR opened on *.sql
       │
       ├──► Branch ruleset auto-requests Copilot as reviewer
       │
       ├──► sql-pr-scan.yml (job: copilot-review-gate)
       │      1. createCommitStatus "SQL Review Tier: pending"
       │      2. Polls /pulls/N/reviews every 20s (up to 10 min)
       │      3. When Copilot review arrives → process_copilot_review.py
       │
       └──► process_copilot_review.py
              • Reads Copilot's review body + inline comments
              • Detects tier from:
                  - markers   [HARD_BLOCK] / [DBA_REVIEW]
                  - phrases   "hard-block" / "dba review"
                  - codes     H1-H7  → HARD_BLOCK
                              D1-D13 → DBA_REVIEW
                  - fallback  any inline finding → DBA_REVIEW
              • Removes prior tier labels
              • Applies new tier label
              • POSTs "SQL Review Tier" commit status
```

| Tier | Label | Status check | Merge |
|---|---|---|---|
| `[HARD_BLOCK]` | `sql-hard-block` | `failure` | ❌ blocked |
| `[DBA_REVIEW]` | `dba-review-required` | `success` | ⚠️ DBA must approve |
| `[CLEAN]` | `sql-scan-clean` | `success` | ✅ ready |

---

## Files shipped in this repo

```
.github/
├── copilot-instructions.md                 ← Copilot review rubric (≤4000 chars)
├── instructions/
│   └── sql.instructions.md                 ← per-rule detail (applyTo: **/*.sql)
├── scripts/
│   └── process_copilot_review.py           ← parser: review → label + status
└── workflows/
    └── sql-pr-scan.yml                     ← workflow: trigger + poll + parse
```

No other files are required.

---

## DevOps enablement checklist

Follow these steps **in order** on the target repository.

### 1. Merge the workflow files

Merge this PR (or copy the four files above into the target repo's default branch).

### 2. Create the GitHub PAT for adding Copilot as reviewer

The default `GITHUB_TOKEN` can add Copilot only to the "Suggestions" panel,
not the formal Reviewers panel. A fine-grained PAT is required.

**Create the PAT:**
1. https://github.com/settings/personal-access-tokens/new
2. Resource owner: the org that owns this repo
3. Repository access: this repo only
4. Permissions:
   - **Pull requests: Read and write**
5. Save the token value.

**Add as repo secret:**
1. Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. Name: `COPILOT_REVIEWER_PAT`
3. Value: paste the PAT
4. Save.

### 3. Enable GitHub Copilot code review on the repo

1. Repo → **Settings** → **Code & automation** → **Copilot** → **Code review**
2. Turn on **"Allow Copilot to review pull requests"**
3. Confirm the org's Copilot Business / Enterprise plan covers this repo.

### 4. Create the three tier labels

Run once (replace `OWNER/REPO`):

```bash
gh label create sql-hard-block       --color B60205 --description "Copilot found ≥1 blocking SQL issue" --repo OWNER/REPO
gh label create dba-review-required  --color FBCA04 --description "Copilot flagged DBA-tier issues"      --repo OWNER/REPO
gh label create sql-scan-clean       --color 0E8A16 --description "Copilot review passed cleanly"        --repo OWNER/REPO
```

### 5. Create the branch ruleset

Repo → **Settings** → **Rules** → **Rulesets** → **New branch ruleset**.

| Setting | Value |
|---|---|
| Ruleset name | `Require Copilot SQL Review` |
| Enforcement status | **Active** |
| Target branches | Default branch (`main`) — add `develop`, `release/*`, `hotfix/*` if used |
| Restrict creations | unchecked |
| Restrict updates | unchecked |
| Restrict deletions | ✅ checked |
| Require linear history | optional |
| Require a pull request before merging | ✅ checked |
| └─ Required approvals | 1 (or more per your policy) |
| └─ Dismiss stale reviews on push | ✅ checked |
| └─ Require review from Code Owners | ✅ checked (recommended) |
| └─ **Automatically request Copilot code review** | ✅ checked |
| Require status checks to pass | ✅ checked |
| └─ Require branches up to date before merging | ✅ checked |
| └─ Status checks required | **`SQL Review Tier`** |

Save the ruleset.

### 6. Verify with a test PR

1. Create a branch with a trivial SQL file:
   ```sql
   -- migrations/V99.0.0__demo.sql
   ALTER TABLE IF EXISTS public.demo ADD COLUMN IF NOT EXISTS test_col SMALLINT;
   ```
2. Open a PR.
3. Within ~2 minutes you should see:
   - Copilot listed in the Reviewers panel
   - `SQL Review Tier: pending` status check
   - Copilot posts inline review (idempotent ADD COLUMN → no findings)
   - `sql-scan-clean` label applied
   - `SQL Review Tier: success` → mergeable

4. Now break it — change `IF NOT EXISTS` to nothing, push:
   - Copilot re-reviews with a `[HARD_BLOCK]` H1 inline comment
   - `sql-hard-block` label applied
   - `SQL Review Tier: failure` → merge blocked ✋

---

## How rules work

Rules are **plain markdown**. To add or change a rule, edit one of two files:

| File | Purpose | Char budget |
|---|---|---|
| `.github/copilot-instructions.md` | Quick reference Copilot sees on every review | ≤4000 chars (GitHub limit) |
| `.github/instructions/sql.instructions.md` | Full per-rule detail (`applyTo: **/*.sql`) | unlimited |

Tier marker conventions in inline comments:

```markdown
[HARD_BLOCK] H3 — DELETE without WHERE will wipe all rows. Add `WHERE …`.
[DBA_REVIEW] D1 — ALTER COLUMN TYPE rewrites the table. Confirm maintenance window.
```

The parser also accepts natural-language phrasing (`hard-block`, `dba review`)
and bare rule codes (`H1`-`H7` / `D1`-`D13`).

---

## Permissions reference

`sql-pr-scan.yml` requests:

| Permission | Used for |
|---|---|
| `contents: read` | Checkout |
| `pull-requests: write` | Read reviews + request Copilot reviewer |
| `issues: write` | Add/remove tier labels |
| `statuses: write` | Post `SQL Review Tier` commit status |

The `COPILOT_REVIEWER_PAT` secret only needs **Pull requests: Read and write**.

---

## Troubleshooting

### `SQL Review Tier` stays `pending` forever
- Confirm Copilot code review is enabled on the repo (step 3).
- Confirm `COPILOT_REVIEWER_PAT` secret exists and isn't expired.
- Check the workflow run log; the `Wait for Copilot review` step prints
  `attempt N/30` lines every 20s. If all 30 attempts elapse without a review,
  Copilot's daily quota may be exhausted.

### Workflow run shows `action_required` ("Approve and run")
- Do **not** add a `pull_request_review` trigger to the workflow. GitHub
  forces a manual approval gate on workflows triggered by bot accounts,
  which is unavoidable. The current polling design avoids this entirely.

### Wrong tier applied
- Read the inline Copilot comment text.
- Confirm tier vocabulary (`hard-block` / `dba review` / `H1-H7` / `D1-D13`) is present.
- The parser is conservative: any unrecognized inline finding falls back to
  `DBA_REVIEW`. Update `.github/copilot-instructions.md` to reinforce
  Copilot's tier-prefix discipline.

### `SQL Review Tier` check missing from PR
- The workflow only runs on PRs that change `**/*.sql` files.
  Pure non-SQL PRs are not gated.

---

## Owner

Platform Engineering — DBA tooling.
Source of truth: this repository.
