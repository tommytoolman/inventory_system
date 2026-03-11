# RIFF Inventory System — Development Workflow Guide

## Overview

This guide defines the development workflow for the RIFF WooCommerce Integration project.
The folder structure separates concerns clearly — new features, bug fixes, general changes,
and versioned snapshots each have a dedicated home. This makes it easy to track progress,
hand off context between sessions, and roll back to a known-good state at any point.

---

## Folder Structure

```
WooCommerce-Integration/
├── features/        # New feature implementations
├── bugfixes/        # Bug fixes and patches
├── changes/         # Refactors, optimisations, documentation updates
├── snapshots/       # Versioned project snapshots for quick restoration
├── inventory_system/  # Core application (FastAPI + WooCommerce integration)
├── discord-logger/    # Discord logging module
└── DEVELOPMENT.md   # This file
```

---

## Folder Purposes

### `/features/`
Work-in-progress and completed new feature implementations.
Each feature lives in its own subfolder, isolated from the main codebase until ready to merge.

**Examples:** `feature-bulk-price-update`, `feature-webhook-retry-logic`, `feature-dashboard-ui`

### `/bugfixes/`
Targeted patches and fixes for known issues.
Keep a brief note at the top of each file describing the bug and the fix applied.

**Examples:** `fix-cart-validation`, `fix-woo-sync-timeout`, `fix-variant-mapping-null`

### `/changes/`
General improvements that are not features or bug fixes — refactors, performance
optimisations, dependency updates, documentation rewrites.

**Examples:** `change-refactor-woo-client`, `change-update-requirements`, `change-docs-api-reference`

### `/snapshots/`
Point-in-time copies of the full project root. Created at meaningful milestones —
after completing a feature, before a risky change, or at the end of a sprint.
Each snapshot is self-contained and restorable.

---

## Naming Conventions

| Folder       | Pattern                              | Examples                              |
|--------------|--------------------------------------|---------------------------------------|
| `features/`  | `feature-[short-description]`        | `feature-bulk-price-update`           |
| `bugfixes/`  | `fix-[short-description]`            | `fix-woo-sync-timeout`                |
| `changes/`   | `change-[short-description]`         | `change-refactor-woo-client`          |
| `snapshots/` | `snapshot-[milestone]-v[N]-[TIMESTAMP]` | `snapshot-woo-commerce-baseline-v1-2026-03-11T10-02-52` |

**Rules:**
- Use lowercase and hyphens only (no spaces, no underscores)
- Keep names short but descriptive — aim for 3–5 words
- Always increment the version number (`v1`, `v2`, `v3`) on snapshots
- Timestamps use ISO 8601 format: `YYYY-MM-DDTHH-MM-SS`

---

## Snapshot Management

### Creating a Snapshot

Run from the project root (Git Bash / terminal):

```bash
TIMESTAMP=$(date -u +"%Y-%m-%dT%H-%M-%S")
SNAPSHOT_NAME="snapshot-[milestone]-v[N]-$TIMESTAMP"
rsync -a --exclude='snapshots' \
  "WooCommerce-Integration/" \
  "WooCommerce-Integration/snapshots/$SNAPSHOT_NAME/"
```

Or tell Claude Code:
> "Create a snapshot of the current project state called snapshot-[milestone]-v[N]"

After creating a snapshot, update `snapshots/SNAPSHOTS.md` with:
- Snapshot name
- Date created
- Description of the project state at that point

### Listing Snapshots

```bash
ls snapshots/
```

Or open `snapshots/SNAPSHOTS.md` for the annotated list.

---

## Snapshot Restoration

If something breaks and you need to restore to the WooCommerce integration baseline:

1. Tell Claude Code: `"Restore project to backup-with-woo-commerce-integration-v1-[TIMESTAMP]"`
2. Claude Code will copy the backup into the project root, replacing current files
3. Confirm the restoration is complete and test the application

To restore from an internal snapshot (e.g. a mid-development checkpoint):

1. Tell Claude Code: `"Restore project to snapshot-woo-commerce-baseline-v1-[TIMESTAMP]"`
2. Claude Code will copy the snapshot contents back to the project root
3. Confirm the restoration is complete and test the application

**Backup locations:**
- **Parent-level escape hatch** (untouched): `RIFF/backup-with-woo-commerce-integration-v1-2026-03-11T10-02-52/`
- **Internal snapshots** (working checkpoints): `WooCommerce-Integration/snapshots/`

---

## Development Session Workflow

A recommended pattern for each development session:

1. **Check current state** — review `snapshots/SNAPSHOTS.md` and open issues
2. **Create a snapshot** before starting any significant work (optional but recommended)
3. **Work in the appropriate folder** — `features/`, `bugfixes/`, or `changes/`
4. **Test changes** against the inventory system
5. **Create a new snapshot** once work is stable
6. **Update `SNAPSHOTS.md`** with a description of what changed

---

## Team Notes

- **Harry** — lead developer
- **Tommy, Simon** — collaborators (share this file when onboarding)
- Any Claude Code session can restore a snapshot by referencing the name above
- Keep `SNAPSHOTS.md` up to date — it's the single source of truth for project history
