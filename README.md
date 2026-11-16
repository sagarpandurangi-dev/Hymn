# Hymn

A personal life copilot: it helps a person follow through on their life across five areas — **Money, Health, Family & Relationships, Learning and Work** — checking plans against their real time and money.

- `backend/` — FastAPI + MongoDB, deployed on Railway from `main` (built and maintained with Claude Code). Working notes: `CLAUDE.md`.
- `frontend/` — the Expo / React Native app (built with Emergent; its latest copy lives on the `emergent-frontend` branch).
- `docs/` — API notes for each area, audits, the beta test plan.

Tests: `cd backend && pytest safety_tests && pytest unit_tests` (offline; no database or AI needed).
