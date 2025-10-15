# Repository Guidelines

## Project Structure & Module Organization
- `app/main.py` bootstraps the FastAPI application; shared settings are under `app/core`, while database wiring stays in `app/database.py` and dependencies in `app/dependencies.py`.
- Business logic belongs in `app/services`, persistence models in `app/models`, validation schemas in `app/schemas`, and HTTP surfaces live in `app/routes` and feature routers inside `app/routers/`.
- Templates, static assets, and auxiliary data mirror runtime paths: `app/templates`, `app/static`, and test fixtures or mocks in `tests/fixtures` and `tests/mocks`.

## Build, Test, and Development Commands
- `uvicorn app.main:app --reload` launches the API locally with live reload for backend iteration.
- `pytest` runs the full suite; scope down with `pytest tests/unit -m unit` or `pytest -m integration` before merging.
- `alembic upgrade head` aligns the database schema, and `./start.sh` reproduces the Railway deployment smoke test.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation; modules use snake_case, classes PascalCase, and constants UPPER_SNAKE_CASE.
- Keep domain types in their homes: SQLAlchemy models in `app/models`, Pydantic schemas in `app/schemas`, routers in `app/routers/<feature>.py`.
- Prefer async/await, add type hints on service boundaries, and run `black` (88-char lines) after grouping imports by stdlib/third-party/local.

## Testing Guidelines
- `pytest` with the built-in async fixtures from `tests/conftest.py` powers unit and integration coverage without custom event loops.
- Name test modules `test_<feature>.py`, mark scope with `@pytest.mark.unit` or `@pytest.mark.integration`, and keep sample payloads in `tests/mocks` or `tests/test_data`.
- Address regressions with companion tests in `tests/unit` or `tests/integration` that exercise the impacted service or router path.

## Commit & Pull Request Guidelines
- Write imperative commit subjects ≤72 chars (e.g., `Add pagination to catalog feed`) and include motivation plus evidence in the body when needed.
- Reference issues with `Refs #123`, list required migrations or scripts, and attach screenshots for template or asset changes.
- Do not request review until `pytest` passes locally and temporary artifacts in `data_export/` or `logs/` are removed.

## Security & Configuration Tips
- Copy `.env.example` to `.env`, supply developer secrets locally, and never commit credentials or connection strings.
- Gate destructive scripts in `scripts/` behind explicit flags, and prefer per-developer PostgreSQL instances for isolation.
- Scrub uploaded data files from `data_export/` before publishing branches or raising a pull request.
