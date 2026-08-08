# Spec 007 — Deploy the backend

Build mode. After this, VOLT runs without your laptop.

**Precondition:** spec 006 complete, committed, pushed. `pytest` and
`flutter analyze` clean.

## Guardrails

- **Never commit the service account JSON.** In deployment it becomes an
  environment variable, not a file. The local file stays gitignored.
- **Do NOT change the Android cleartext config yet.** Local development still
  needs it. Production uses HTTPS, which is allowed by default.
- **Do NOT deploy the Flutter app anywhere.** Backend only.
- Verify current Render pricing and free-tier terms before creating paid
  resources: https://render.com/pricing

## What has to change and why

| Local | Deployed | Why |
|---|---|---|
| `.env` file | Dashboard environment variables | No file system to put secrets in |
| Service account JSON file | JSON in an env var | Same |
| Port 8000 | `$PORT` from the platform | Render assigns the port |
| `postgresql+asyncpg://` hand-written | Provided URL, scheme rewritten | Render emits `postgresql://` |
| Migrations run manually | Run on every deploy | Nobody is there to run them |
| Unpinned dependencies | Pinned | A silent major-version bump breaks the build |

---

## Step 1 — Pin dependencies

Unpinned versions mean a deploy months from now installs different packages
than your laptop has, and the failure looks like a code bug.

From `volt-backend/` with the venv active:

```powershell
pip freeze > requirements-lock.txt
```

Then hand-edit `requirements.txt` to pin **only the direct dependencies** to
the versions in the lock file, using `==`. Do not replace `requirements.txt`
with the full freeze output — it includes transitive dependencies and becomes
unmaintainable.

Direct dependencies: fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg,
alembic, pydantic-settings, firebase-admin, pytest, pytest-asyncio.

Delete `requirements-lock.txt` afterwards.

## Step 2 — Pin the Python version

**New file: `volt-backend/.python-version`**

Containing the Python major.minor you develop against. Check with
`python --version` and use e.g.:

```
3.13
```

Without this, the platform picks a default that may not match, and a version
mismatch surfaces as a confusing dependency error.

## Step 3 — Accept credentials from an environment variable

**Edit `volt-backend/app/config.py`:**

Add alongside the existing path setting:

```python
    # Deployment: full service account JSON as a string. Takes precedence over
    # the file path when set, because there is no file system to write to.
    firebase_credentials_json: str | None = None
```

**Edit `volt-backend/app/auth.py`**, in `init_firebase()`:

```python
import json

def init_firebase() -> None:
    if firebase_admin._apps:
        return

    settings = get_settings()
    if settings.firebase_credentials_json:
        cred = credentials.Certificate(
            json.loads(settings.firebase_credentials_json)
        )
    else:
        cred = credentials.Certificate(settings.firebase_credentials_path)

    firebase_admin.initialize_app(cred)
```

`credentials.Certificate` accepts either a path or a dict — verify that against
the installed `firebase-admin` before relying on it.

## Step 4 — Normalise the database URL

Render emits `postgresql://…`. SQLAlchemy needs `postgresql+asyncpg://…`, and
asyncpg rejects the `sslmode` query parameter that some providers append.

**Edit `volt-backend/app/config.py`** — add a field validator on
`database_url` that:

1. Rewrites a leading `postgres://` or `postgresql://` to `postgresql+asyncpg://`
2. Strips any `sslmode` query parameter

Use Pydantic v2's `field_validator` with `mode="before"`. Verify the API
against the installed pydantic version rather than assuming.

Add a unit test in `tests/` covering: plain `postgresql://`, the legacy
`postgres://`, a URL with `?sslmode=require`, and an already-correct
`postgresql+asyncpg://` passing through unchanged.

## Step 5 — Blueprint file

**New file: `volt-backend/render.yaml`**

```yaml
services:
  - type: web
    name: volt-api
    runtime: python
    rootDir: volt-backend
    plan: free
    buildCommand: pip install -r requirements.txt
    preDeployCommand: alembic upgrade head
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /api/v1/health
    envVars:
      - key: ENVIRONMENT
        value: production
      - key: DATABASE_URL
        fromDatabase:
          name: volt-db
          property: connectionString
      - key: FIREBASE_CREDENTIALS_JSON
        sync: false

databases:
  - name: volt-db
    plan: free
```

`sync: false` means the value is set in the dashboard and never lives in this
file. That is what keeps the service account key out of git.

**Verify this schema against Render's current blueprint reference** —
https://render.com/docs/blueprint-spec — field names change, and
`preDeployCommand` availability may depend on plan.

## Step 6 — Startup must not crash on a missing key

If `FIREBASE_CREDENTIALS_JSON` is unset, `init_firebase()` will raise and the
service will crash-loop with an unhelpful log line.

Make the lifespan handler log a clear, explicit error naming the missing
variable before re-raising. A deploy that fails should say why in the first
line of its log.

## Step 7 — Create the deployment

1. https://dashboard.render.com → **New → Blueprint**
2. Connect your GitHub account, authorise the `volt` repository
3. Select the repo. Render reads `render.yaml`
4. It will prompt for `FIREBASE_CREDENTIALS_JSON` because of `sync: false`

For that value: open `volt-backend/secrets/firebase-service-account.json`,
copy the **entire contents including braces**, paste as the value. It is a
multi-line JSON string; Render handles that.

**Do not paste it anywhere else.** Not into chat, not into a file, not into a
commit.

5. Apply. First deploy takes several minutes.

## Step 8 — Watch the deploy log

In order, you should see: dependencies installing, `alembic upgrade head`
applying three migrations, uvicorn starting, health check passing.

Common failures and their cause:

| Log line | Cause |
|---|---|
| `ModuleNotFoundError` | Missing from `requirements.txt` |
| `InvalidCatalogNameError` | `DATABASE_URL` not wired to the database |
| `Invalid dialect` or asyncpg errors | Step 4's URL rewrite not working |
| `ValueError` from `credentials.Certificate` | JSON pasted incomplete |
| Health check timeout | Not binding `$PORT`, or bound to `127.0.0.1` |

## Step 9 — Verify the deployed API

Your URL will be something like `https://volt-api.onrender.com`.

```powershell
curl.exe https://volt-api.onrender.com/api/v1/health
```

Expect `{"status":"ok","environment":"production"}`. Note **production** — if
it says development, `ENVIRONMENT` did not take, and `echo=True` is logging
every SQL statement in a live service.

Then confirm the data:

```powershell
curl.exe -X POST https://volt-api.onrender.com/api/v1/bookings/estimate -H "Content-Type: application/json" -d "{\"pickup\":{\"address\":\"Koramangala\",\"lat\":12.9352,\"lng\":77.6245},\"drop\":{\"address\":\"Whitefield\",\"lat\":12.9698,\"lng\":77.75}}"
```

Three options with the same fares as local proves the seed migration ran on the
new database.

Then, in browser, `https://volt-api.onrender.com/docs` — auth should still be
enforced. A `POST /bookings` without a token must return 401.

## Step 10 — Point the app at it

```powershell
cd $env:USERPROFILE\projects\volt\customer_app
flutter run -d RMX3371 --dart-define=API_BASE_URL=https://volt-api.onrender.com
```

Note **https** and no port. Full walkthrough: sign in, pickup, drop, goods,
weight, vehicle, confirm. The booking now persists on a server you are not
running.

**Turn your laptop's uvicorn off first** so you cannot accidentally be testing
against local.

**Expect the first request to be slow** on a free plan — the service sleeps
when idle and cold-starts in 30–60 seconds. Your app's 10-second connect
timeout may fire. Either raise it, or know to retry once.

## Step 11 — A build script, so nobody memorises the URL

**New file: `customer_app/run-local.ps1`**
```powershell
flutter run -d RMX3371 --dart-define=API_BASE_URL=http://192.168.1.8:8000
```

**New file: `customer_app/run-prod.ps1`**
```powershell
flutter run -d RMX3371 --dart-define=API_BASE_URL=https://volt-api.onrender.com
```

Commit both. Your friends will need them, and the LAN IP in the local one is
per-machine — note that in a comment.

## Step 12 — Update `CLAUDE.md`

```
Deployed: backend on Render at https://volt-api.onrender.com, managed Postgres.
Migrations run via preDeployCommand on every deploy. Secrets are dashboard env
vars, not files — FIREBASE_CREDENTIALS_JSON holds the service account JSON.
Free plan: service sleeps when idle, first request after idle is slow.
Run app against prod: ./run-prod.ps1   Against local: ./run-local.ps1
```

## Step 13 — Report and stop

1. Files created and edited
2. The deployed URL, and the health endpoint's actual response
3. Deploy log confirmation that all three migrations applied
4. The estimate response from production, compared to local
5. Confirmation that `POST /bookings` without a token returns 401 in production
6. Whether the app worked end to end against the deployed URL
7. Any deviation, and why

Do not add status polling — that is spec 008.
