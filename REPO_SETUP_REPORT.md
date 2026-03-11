# RIFF-Live-Repo — Setup Report
**Date:** 2026-03-11
**Repository:** https://github.com/Harrygithubportfolio/RIFF-Live-Repo
**Git Root:** `WooCommerce-Integration/` (parent folder)

---

## What Was Done

1. Removed the embedded `.git` folder from `inventory_system/` (it had its own git history)
2. Initialised a fresh git repo at `WooCommerce-Integration/`
3. Created a `.gitignore` excluding sensitive/large files
4. Committed all 775 project files in an initial commit
5. Pushed to GitHub at the URL above
6. Set up 3 branches (see below)

---

## Branch Structure

```
main                          ← Production. Railway deploys from here.
 └── develop                  ← Integration. All new work branches off here.
      └── fix/sales-duplicates-issue-14  ← Current fix (already in main baseline)
```

### `main`
- **Purpose:** Always production-ready. Deploys to Railway automatically on push.
- **Rule:** Only merge here when code is tested and working.
- **Current state:** Full project baseline + sales duplicates fix (Issue #14) included.

### `develop`
- **Purpose:** Integration branch. Day-to-day development work happens here.
- **Rule:** Branch off `develop` for every new feature or fix. Merge back to `develop` when done, then to `main` when ready to deploy.
- **Current state:** Identical to `main` at this point (starting point for all future work).

### `fix/sales-duplicates-issue-14`
- **Purpose:** Documents the sales & ended listings duplicates fix.
- **Current state:** Same as `main` (the fix was part of the initial commit).
- **Future use:** When you work on the next fix, create a new branch like `fix/platform-coverage-#15`.

---

## Day-to-Day Workflow

### Starting a new bug fix
```bash
cd C:/Users/harry/Documents/ActionSmartAI/RIFF/WooCommerce-Integration
git checkout develop
git pull origin develop
git checkout -b fix/short-description-issue-N
# make your changes
git add <files>
git commit -m "fix: description of fix (Issue #N)"
git push origin fix/short-description-issue-N
```

### Starting a new feature
```bash
git checkout develop
git checkout -b feature/short-description
# make your changes
git add <files>
git commit -m "feat: description of feature"
git push origin feature/short-description
```

### Deploying to production
```bash
git checkout main
git merge develop          # or merge the specific branch
git push origin main       # Railway auto-deploys within ~2 minutes
```

---

## Railway Configuration

> **Important:** Because the git root is `WooCommerce-Integration/` but the deployable app
> is in `inventory_system/`, Railway needs to know where to find the app.

In your Railway project settings, set:
- **Root Directory:** `inventory_system`
- **Build Command:** (Railway auto-detects from `Dockerfile` or `requirements.txt`)
- **Branch:** `main`

Railway will then look for `inventory_system/Dockerfile` (or `requirements.txt`) as the entry point.

---

## What Was Excluded from Git

| Excluded | Why | Size |
|----------|-----|------|
| `snapshots/` | Point-in-time project copies — not source code | 460 MB |
| `inventory_system/data_export/` | Exported database records (products, orders, customers) | 60 MB |
| `inventory_system/data/reverb/` `data/vr/` `data/ebay/` | Raw platform CSV/API dumps | 42 MB |
| `inventory_system/scripts/backup/db/*.sql` | Full DB backups (>50MB each, GitHub limit) | ~155 MB |
| `venv/` | Python virtual environment | — |
| `__pycache__/` `*.pyc` | Python bytecode | — |
| `*.db` `*.sqlite` | SQLite test database | — |
| `inventory_system/logs/` | Runtime logs | — |
| `inventory_system/tmp/` | Temporary files | — |
| `node_modules/` | Node packages (discord-logger) | — |
| `.env` / `*.env` | Secrets — never committed | — |

`.env.example` files **are** included (they show structure without real secrets).

---

## Files Included (775 total)

| Folder | Contents |
|--------|----------|
| `inventory_system/app/` | Core FastAPI app (routes, models, services, templates, static) |
| `inventory_system/alembic/` | Database migrations |
| `inventory_system/scripts/` | Sync schedulers, maintenance scripts, platform scripts |
| `inventory_system/tests/` | Unit and integration tests |
| `inventory_system/docs/` | Architecture docs, platform integration guides, API reference |
| `inventory_system/woocommerce/` | WooCommerce-specific module |
| `inventory_system/.claude/` | Claude Code prompts and bug diagnostic files |
| `discord-logger/` | TypeScript Discord logging module |
| `bugfixes/` `features/` `changes/` | Development workflow folders |
| `DEVELOPMENT.md` | Project workflow guide |
| `.gitignore` | Git exclusion rules |

---

## Commits on Main

| Hash | Message |
|------|---------|
| `ab104dd` | `feat: initial commit — RIFF inventory system v1` (775 files) |
| `c16df6e` | `chore: exclude large SQL backup files from git (>50MB)` |

---

## Bug Fixes Included in Baseline

### Issue #14 — Sales & Ended Listings Duplicates

**Files changed:**
- `inventory_system/app/routes/reports.py` (lines 2067, 2256)
- `inventory_system/app/services/woocommerce/importer.py`

**Root cause:** Report query used `PARTITION BY p.id, DATE(detected_at)` — one row per product
per day. Sold items re-detected on each hourly sync appeared multiple times.

**Fix:** Changed to `PARTITION BY p.id` — one row per product overall. Sold events
prioritised over ended; most recent wins on tie. WooCommerce importer also fixed to use
`INSERT ... ON CONFLICT DO NOTHING` instead of unprotected `session.add()`.

---

## Next Steps

```
Remaining fixes (from RIFF_LIVE_REPO_WORKFLOW_FINAL.md):
5. Platform Coverage Mismatch
6. Listing Health Mismatches
7. CrazyLister Template Coverage
8. Product Code Searchability
9. Sales Reports Time Period Selection
10. Multi-User Setup (Research)
11. Messaging Integration (Research)
```

For each: `git checkout develop → git checkout -b fix/name-issue-N → fix → push → merge to main`.

---

## GitHub Actions (Future)

When you're ready, add `.github/workflows/deploy.yml` to auto-run tests on every push
to `develop` before merging to `main`. This will make the pipeline fully automated.
