# Working with Emergent

Hymn is built by two agents: Emergent (UI, preview) and Claude Code
(backend, integrations, tests). Emergent saves to GitHub but cannot pull
changes back, so the two must never edit the same files.

## Ownership

| Path        | Owner       | Notes                                              |
|-------------|-------------|----------------------------------------------------|
| `backend/`  | Claude Code | Emergent must not modify it.                       |
| `frontend/` | Emergent    | Claude Code changes it only when asked explicitly. |
| `main`      | Claude Code | Changes land through reviewed PRs.                 |

## Flow

1. Emergent works and saves to its own branch (it names them
   `conflict_*` when it can't save on top of `main`).
2. Claude Code merges only `frontend/` from that branch into `main`.
3. Nothing flows back to Emergent; its copy of `backend/` goes stale on
   purpose. Once the backend is hosted outside Emergent, point Emergent's
   `EXPO_PUBLIC_BACKEND_URL` at it so its preview uses the real API.

## Prompt preamble for every Emergent task

> Do not modify anything under `backend/`, even if something there looks
> broken; report it instead. Only change files under `frontend/`.
> Use the API contract below as-is.

Follow it with: the screen to build, the endpoints and fields it uses,
and what is out of scope. Small, precise prompts cost fewer credits.

## Checks

`.github/workflows/backend-tests.yml` runs the offline suites on every PR:

```sh
cd backend
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest safety_tests
python -m pytest unit_tests
```

`backend/tests/` and `tests/` are live integration suites that need a
running server; they are not part of CI.
