# Hymn

This repository is configured for local-only development. The local database,
backend, frontend, authentication, planning, and tests use your computer only.
No hosted preview, authentication, planning, or database service is required.

## One-time Windows setup

Ask a technical helper to install these standard tools:

1. Docker Desktop for Windows.
2. Python 3.12, with the Python launcher and `pip`.
3. Node.js 22 LTS.
4. Yarn 1.22.22. Node includes Corepack, which can install the repository's
   exact declared Yarn version. Open PowerShell and run:

```powershell
corepack enable
corepack prepare yarn@1.22.22 --activate
```

Check the result with `yarn --version`. It must print `1.22.22`.

Then open PowerShell in this repository and run:

```powershell
.\scripts\local.cmd setup-env
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-local.txt
Set-Location frontend
yarn install --frozen-lockfile
Set-Location ..
```

The setup command creates ignored local environment files from safe examples.
Open `backend\.env` and replace the placeholder `JWT_SECRET` with a long,
random value used only on this computer. Never paste production credentials
into these files. The example CORS settings allow only the listed local
frontend addresses.

## Start Hymn

Start Docker Desktop first. In PowerShell:

```powershell
.\scripts\local.cmd db-start
```

Open a second PowerShell window:

```powershell
.\scripts\local.cmd backend
```

Open a third PowerShell window:

```powershell
.\scripts\local.cmd frontend
```

The backend listens only on `127.0.0.1:8001`. MongoDB is exposed only on
`127.0.0.1:27017`.

## Authentication and planning

Hymn uses email/password accounts and signed JWTs. Logout is stateless: the
app deletes its locally stored JWT, and the backend confirms the logout
request. Password recovery currently uses security questions. That recovery
method is temporary and is not suitable for a public release; replace it with
a verified email recovery flow before public deployment.

Planning analysis and generation are local and deterministic. Generation
preserves confirmed objectives and capacity calculations, but it will ask for
missing plan items instead of inventing tasks or contacting an external AI
provider.

## Stop Hymn

Press Ctrl+C in the backend and frontend windows. Then run:

```powershell
.\scripts\local.cmd db-stop
```

Your local data remains available for the next start.

## Tests and checks

Tests intentionally refuse hosted backend URLs, non-local MongoDB hosts, and
any database name other than `hymn_test`.

Start the database and backend with the test environment:

```powershell
.\scripts\local.cmd db-start
```

In the backend window, start the isolated test backend:

```powershell
.\scripts\local.cmd backend-test
```

In another window:

```powershell
.\scripts\local.cmd test
.\scripts\local.cmd lint
```

The application database is `hymn_local`. Tests use the separate `hymn_test`
database.

## Status and reset commands

```powershell
.\scripts\local.cmd db-status
.\scripts\local.cmd reset-db
```

`reset-db` requires typing an exact confirmation phrase. It deletes only the
Docker volume named `hymn-local-mongodb-data`, then recreates the two local
databases. It does not affect any remote or production database.

## Public deployment requirements

Production mode intentionally refuses to start unless both of these are set:

- `JWT_SECRET`: a strong deployment-only secret.
- `CORS_ALLOWED_ORIGINS`: an explicit comma-separated list of the deployed
  frontend origins. Wildcards are rejected.

Do not reuse local or test secrets in a deployment.
