# Repository Guidelines

## Project Structure & Module Organization

- `main.py` is the executable entry point; it starts the PySide6 application in `tagger/app.py`.
- `tagger/` contains the application package. `main_window.py` and feature-dialog modules implement the UI; `domain.py`, `catalog.py`, `storage.py`, and `paths.py` hold core data and filesystem behavior; `settings.py`, `tag_library.py`, and `preview.py` provide supporting services.
- `tests/` contains pytest tests. `test_domain.py`, `test_storage.py`, and `test_paths.py` cover non-UI behavior; `test_qt_ui.py` covers dialogs and main-window workflows.
- `data/` is the default runtime data directory for settings and the downloaded tag library; use `TAGGER_DATA_DIRECTORY` for isolated or temporary data.

## Build, Test, and Development Commands

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+:

```powershell
uv sync                  # install the default environment
uv sync --all-groups     # also install optional AI-tagging dependencies
uv run python .\main.py # launch the desktop app
.\.venv\Scripts\python.exe -m pytest # run the complete test suite
.\.venv\Scripts\ty.exe check       # run the repository's type checker
```

When changing dependency constraints or the PyTorch index, run `uv lock` and sync again.

## Coding Style & Naming Conventions

Follow the existing Python style: four-space indentation, type hints, and `from __future__ import annotations`. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and uppercase names for constants. Keep Qt signal/slot behavior close to its widget and preserve the UI/domain/storage separation. Match neighboring files because no formatter or linter is configured.

## Testing Guidelines

Tests use pytest and pytest-qt. The venv command above disables pytest's cache provider. The shared fixture creates isolated data under ignored `tests/.pytest-tmp-local/`, sets Qt to offscreen, and redirects application data there, so tests avoid local `data/` files and a desktop. Name files `test_*.py` and tests `test_<behavior>`. Add focused domain/storage tests for logic changes and Qt tests for user-facing behavior; no coverage threshold is defined.

## Commit & Pull Request Guidelines

Use a short imperative subject with the existing category prefix, for example `feat: add recent-folder cleanup`, `fix: preserve tag order`, or `docs: update setup steps`. Keep unrelated changes out of the commit. Pull requests should explain the change, link an issue when applicable, and list tests run. For UI changes, attach a screenshot or short recording and note platform-specific behavior.

## Security & Configuration Tips

Complex-filter and bulk-operation dialogs execute user-provided Python scripts; treat scripts and opened folders as trusted input. Do not commit credentials, proxy URLs, model caches, or generated `data/` files. Use a separate `TAGGER_DATA_DIRECTORY` for settings, downloads, or destructive-operation tests.
