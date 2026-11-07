# Putting the Hymn backend on Railway

Railway runs the backend all day on the internet. You need three things
saved in your notes first:

| What | Where you got it | Looks like |
|---|---|---|
| Anthropic API key | console.anthropic.com → API Keys | `sk-ant-…` |
| MongoDB connection string | Atlas → Connect → Drivers | `mongodb+srv://hymn:<db_password>@…` |
| MongoDB password | Atlas, when you created the database user | random letters |

In the connection string, replace `<db_password>` (including the `< >`)
with your MongoDB password.

Button names on Railway change from time to time; if one is missing, look
for the closest match or send a screenshot (with no keys visible).

## 1. Create the project

1. On railway.app, click **New Project**, then **Deploy from GitHub repo**.
2. Pick **Hymn**. If it is not listed, click **Configure GitHub App** and
   give Railway access to the Hymn repository.
3. Railway starts building straight away. The first build will fail:
   that is expected until steps 2 and 3 are done.

## 2. Point it at the backend folder

1. Click the Hymn box (the service), then **Settings**.
2. Find **Root Directory**, type `backend`, and save.

Railway then finds `backend/Dockerfile` and builds from it.

## 3. Add the settings (Variables)

Click **Variables**, then add each row below with **New Variable**:

| Name | Value |
|---|---|
| `MONGO_URL` | your MongoDB connection string (with the password filled in) |
| `DB_NAME` | `hymn` |
| `JWT_SECRET` | a long random password, at least 48 characters (use a password manager's generator) |
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `HYMN_RUNTIME_MODE` | `production` |

Never put these values anywhere else: not in chat, not in GitHub, not in
Emergent. If one leaks, create a new one on that website and replace it here.

Railway redeploys after you add variables.

## 4. Give it a web address

1. **Settings** → **Networking** → **Generate Domain**.
2. You get an address like `hymn-production-1234.up.railway.app`.

## 5. Check it works

Open `https://<your address>/api/` in a browser. You should see:

```json
{"message": "Hymn API"}
```

If you see an error instead, open **Deployments** → the latest one →
**View logs**, and send a screenshot of the last lines (check no keys are
visible first).

## What doesn't work yet on Railway

- The planning chat and goal merge still use Emergent's AI wrapper, which
  only exists inside Emergent. They show "Planning is unavailable" until
  they are moved to the Anthropic SDK like the inbox.
- Your existing data lives in Emergent's database. The Railway backend
  starts empty; moving data across is a separate step.
