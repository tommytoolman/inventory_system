# Repository Guidelines

## Project Structure & Module Organization
- `app/main.py` hosts the FastAPI app; shared config sits in `app/core`, DB wiring in `app/database.py`, and reusable dependencies in `app/dependencies.py`.
- Business logic lives in `app/services`, persistence in `app/models`, validation in `app/schemas`, and HTTP handlers under `app/routes` plus `app/routers`.
- Templates and assets stay in `app/templates` and `app/static`; tests mirror the runtime layout via `tests/unit`, `tests/integration`, and reusable data in `tests/fixtures` and `tests/mocks`.

## Build, Test, and Development Commands
- `uvicorn app.main:app --reload` runs the local API with hot reload and is the default dev entry point.
- `pytest` executes the suite; narrow scope with `pytest tests/unit -m unit` or `pytest -m integration`.
- `alembic upgrade head` syncs the schema before integration work, and `./start.sh` mirrors the Railway deploy command for smoke tests.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation; modules stay snake_case, classes PascalCase, and constants UPPER_SNAKE_CASE.
- Keep new types in their domain homes: SQLAlchemy models in `app/models`, Pydantic schemas in `app/schemas`, routers in `app/routers/<feature>.py`.
- Prefer async/await patterns, include type hints on service boundaries, and run `black` (88-character lines) before committing; group imports stdlib/third-party/local.

## Testing Guidelines
- Async tests should rely on fixtures provided in `tests/conftest.py`; avoid spinning custom event loops or sessions.
- Name files `test_<feature>.py` and mark intent with `@pytest.mark.unit` or `@pytest.mark.integration` to align with `pytest.ini` filters.
- Store canned payloads in `tests/mocks` or `tests/test_data`, and add regression coverage when fixing sync defects in `app/services`.

## Commit & Pull Request Guidelines
- Use imperative, present-tense commit titles similar to `Skip confirmation when creating listings`; keep subjects ≤72 characters.
- Include motivation, key changes, and test evidence in the body or PR description, referencing issues with `Refs #123` when needed.
- Call out required migrations or scripts, attach screenshots for template changes, and ensure `pytest` (or CI) is green before requesting review.

## Environment & Security Notes
- Copy `.env.example` to `.env`, supply local secrets, and keep credentials out of Git; favor per-developer PostgreSQL instances.
- Clean temporary artifacts in `data_export/` and `logs/` before opening a PR, and gate destructive scripts in `scripts/` behind explicit flags.
