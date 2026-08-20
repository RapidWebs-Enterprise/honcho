# Reranker unit tests — isolation note

These tests are **pure unit tests** of the `src/reranker_client` HTTP wrapper.
They mock `httpx` at the network boundary and require **only**:

- `httpx`
- `pydantic` + `pydantic-settings` + `python-dotenv` (for `src.config`)
- `pytest` + `pytest-asyncio`

They deliberately live **outside** `tests/` (in `_unittests/reranker/`) because
the project's root `tests/conftest.py` imports the full FastAPI/SQLAlchemy app
(building a live test Postgres DB), which is heavy and cannot run on the 4GB
workstation. These isolated unit tests are the same ones the project's CI will
run under the full test harness.

Run them from the repo root:

```bash
HONCHO_CONFIG_TOML_DISABLED=1 .venv/bin/python -m pytest _unittests/reranker -q
```

(`HONCHO_CONFIG_TOML_DISABLED=1` prevents an absent/fake local `config.toml`
from breaking `src.config`; the settings defaults are used.)