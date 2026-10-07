# driver_app tests

## Regenerating `test/fixtures/drivers_me_403.json`

The bodies in that file are **recorded from real servers**, not written by
hand. That is the point of them: the bug they exist for was an app that
required a field the deployed server did not send, and every hand-written
fixture in the suite agreed with the app rather than with production.

Each entry is the literal response text a real FastAPI app returned over a real
HTTP request to `GET /api/v1/drivers/me`, with a valid token for a uid that has
no `drivers` row.

- `coded` — this branch. `detail` is a string, `code` is a sibling.
- `legacy` — a revision with no `code` field at all, captured from a git
  worktree of what was deployed. Keep an entry like this for as long as any
  server or APK without the code can still be reached.

To re-record, run the app under `unittest.mock.patch` of
`app.auth.firebase_auth.verify_id_token` (the local service account key cannot
mint a token) and capture `response.text` verbatim. For the legacy entry, do it
from `git worktree add --detach <deployed-rev>` so the body comes from the real
revision rather than from a reconstruction of it.

**Do not edit the bodies by hand.** A fixture that is typed out is a statement
about what someone believed the server sends; a recorded one is evidence.
