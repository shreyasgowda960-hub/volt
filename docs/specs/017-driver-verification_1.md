# Spec 017 — Driver document verification

Build mode. Backend and driver app. This is the last hard blocker before
anyone who is not the owner does a real delivery.

**Precondition:** spec 016 merged. `pytest` clean.

---

## What this replaces

`is_verified` is set `True` at registration, with a comment saying so. There is
no licence check, no RC check, no photo, no review. Any phone number can
register as a driver and immediately claim jobs.

After this spec, a driver uploads documents, the account sits pending until a
human approves it, and `get_current_driver` keeps rejecting unverified drivers
exactly as it does today.

---

## New concepts introduced here

1. **A review state machine on a person, not a booking.** `pending →
   submitted → approved | rejected`, with rejection carrying a reason and
   allowing resubmission. Unlike the booking lifecycle, this one loops.
2. **File upload as a separate concern from the record.** The image lives in
   object storage; the database holds a reference, a status and an audit
   trail. Mixing them means a failed upload leaves a half-written row.
3. **Signed URLs.** A driver's licence must not be readable by anyone with the
   URL. Storage rules deny public reads, and the backend issues short-lived
   signed URLs for the reviewer.
4. **Personal data has a lifetime.** Under the DPDP Act, documents are
   retained for a stated purpose and deleted when that purpose ends. This is
   the first data in VOLT with a legal retention obligation, so the deletion
   path is part of the spec rather than a later cleanup.

---

## Guardrails

- **Do NOT collect Aadhaar, PAN, or any government identity number.** Decided
  deliberately — see the deferral section. If the schema tempts you toward a
  generic `document_type` enum that would admit Aadhaar later, that is fine,
  but do not add the value now.
- **Do NOT build an admin dashboard.** Review happens through a protected
  endpoint. The React dashboard is phase 5.
- **Do NOT change the booking lifecycle, the job board, or fare logic.**
- **Do NOT make documents readable without authentication.** Not "hard to
  guess" — actually denied.
- **Do NOT auto-approve anything**, including in tests. A test that approves
  by shortcut hides the thing this spec exists to enforce.
- New dependencies: only what Firebase Storage requires. Name it and say what
  it replaces.
- Branch: `feat/driver-verification`. Tell me before pushing.

---

## Decisions already made — implement, do not re-litigate

| Decision | Value |
|---|---|
| Documents required | Driving licence, vehicle RC. Both mandatory |
| Storage | Firebase Storage, same project |
| Review | Manual, by the owner, through a protected endpoint |
| Approval effect | `is_verified` becomes true only on approval |
| Rejection | Carries a reason, driver may resubmit |
| Existing drivers | Grandfathered — see step 1 |

---

## Step 0 — Report before building

Read and report:

1. The current `drivers` table columns, and where `is_verified=True` is set
2. How `get_current_driver` uses `is_verified`, and what the driver app does
   with the 403
3. Whether the driver app has any file-picking or camera capability today
4. Whether Firebase Storage is enabled on the project — if it needs console
   setup, say so, because that is mine to do

Do not write code until this is reported.

---

## Step 1 — Migration

**New table `driver_documents`:**

- `id` — PK
- `driver_id` — FK to `drivers`, indexed
- `document_type` — enum: `driving_licence`, `vehicle_rc`
- `storage_path` — the Firebase Storage object path, not a URL. URLs expire;
  paths do not
- `document_number` — nullable string. The licence or RC number as typed by
  the driver, for the reviewer to cross-check against the image
- `status` — enum: `submitted`, `approved`, `rejected`
- `rejection_reason` — nullable text
- `uploaded_at`, `reviewed_at` — nullable timestamps
- `reviewed_by` — nullable, free text for now. There is no admin user table
- Partial unique index: one non-rejected document per `(driver_id,
  document_type)`. A driver may resubmit after rejection, but cannot have two
  live licences pending.

**Changes to `drivers`:**

- `verification_status` — enum: `pending`, `submitted`, `approved`,
  `rejected`, not null, default `pending`
- Keep `is_verified`. It becomes derived from `verification_status ==
  approved` and stays as the thing `get_current_driver` checks, so no auth
  code changes shape.

**Grandfathering:** existing driver rows have `is_verified=True` from the old
auto-approve. Set their `verification_status` to `approved` in the migration
so the owner's own test driver does not lock itself out mid-demo. Add a
comment saying this is a one-time data migration for pre-spec-017 rows and
must not be repeated.

Generate with `--autogenerate`, read it before applying, then round-trip:
`upgrade`, `downgrade -1`, `upgrade`. That habit exists because a migration
that reads correctly can still fail on Postgres enums.

---

## Step 2 — Firebase Storage rules

**This is the security centre of the spec.**

Storage rules must **deny all client reads and writes** on the documents path.
Uploads go through the backend using the service account; reads happen through
backend-issued signed URLs.

Do not let the driver app write directly to Storage with the client SDK. It is
tempting and it is wrong here: a client that can write can usually be made to
write elsewhere, and there is no server-side validation of what landed.

Path convention: `driver-documents/{driver_id}/{document_type}/{uuid}`. The
uuid means a resubmission never overwrites the rejected original, which
matters if a rejection is ever disputed.

Report the rules you write. I will apply them in the console if they need to
be applied there.

---

## Step 3 — Upload endpoint

`POST /api/v1/drivers/me/documents` — driver auth, multipart.

Takes `document_type`, the file, and optional `document_number`.

Validation, all server-side:

- Content type must be image/jpeg, image/png, or application/pdf. Check the
  actual bytes, not the declared header — a declared content type is
  caller-controlled
- Size cap. Pick one and say why. Phone camera images are several MB; a cap
  that rejects real photos is worse than useless
- Reject if a `submitted` or `approved` document of that type already exists,
  with a clear message

On success: upload to Storage, write the row, set the driver's
`verification_status` to `submitted` once both document types are present.

**Order matters.** Upload first, then write the row. A row pointing at an
object that does not exist is worse than an orphaned object, because the
reviewer sees a broken record rather than a missing one. Note in a comment
that orphaned objects on a failed write are accepted debt.

`GET /api/v1/drivers/me/documents` — the driver's own documents, with status
and rejection reason. No signed URLs here; a driver does not need to re-read
their own upload, and issuing URLs widens the surface for no gain. If you
disagree, argue it rather than implementing it.

---

## Step 4 — Review endpoints

These are the owner's, and there is no admin user model. Protect them with a
shared secret in an env var — `ADMIN_REVIEW_TOKEN` — checked as a header.

Say plainly in a comment that this is interim, that a single shared secret has
no audit trail and cannot be revoked per-person, and that it is replaced by
real admin auth when the dashboard arrives. Add it to `.env.example` and to
`docs/future-plans.md`.

- `GET /api/v1/admin/drivers/pending` — drivers with `verification_status =
  submitted`, with their documents and **short-lived signed URLs** for each
  image. State the expiry you chose
- `POST /api/v1/admin/drivers/{driver_id}/approve` — all documents to
  `approved`, driver to `approved`, `is_verified` true
- `POST /api/v1/admin/drivers/{driver_id}/reject` — takes a reason and which
  documents failed. Driver to `rejected`, `is_verified` false

Rejection reason is shown to the driver, so it has to be usable: "licence
photo is blurry" not "invalid".

---

## Step 5 — Driver app

Registration currently ends at the home screen. It now ends at a document
upload screen.

**Routing gains a fourth state.** Today it is: signed out, signed in without a
profile, registered. Now:

```
session == null                              → PhoneEntryScreen
profile == null                              → DriverRegistrationScreen
verification_status in (pending, rejected)   → DocumentUploadScreen
verification_status == submitted             → PendingReviewScreen
verification_status == approved              → DriverHomeScreen
```

`DocumentUploadScreen` — two slots, licence and RC. Each shows empty,
uploading, uploaded, or rejected-with-reason. Camera or gallery. Show the
selected image before upload so a driver can see they picked the wrong one.

`PendingReviewScreen` — plain, honest, no spinner implying anything is
happening. Tell the driver their documents are being reviewed and roughly how
long. A pull-to-refresh is enough; do not poll.

**A rejected driver lands back on the upload screen** with the reason visible
against the specific document that failed.

Follow the existing conventions: no business logic in widgets, repository
handles the calls, and the upload action is `ref.read` inside the button
handler, never a provider — Riverpod's auto-retry would re-upload.

---

## Step 6 — Tests

- Unverified driver cannot claim a job. Assert on the existing 403 path, so a
  regression in `get_current_driver` fails here
- Upload rejected for a bad content type, detected from bytes not header
- Upload rejected when one is already `submitted`
- `verification_status` becomes `submitted` only when **both** documents exist
- Approve sets `is_verified` true; reject sets it false and stores the reason
- A rejected driver can resubmit, and the old row remains
- Review endpoints return 401 without the admin token
- **Signed URLs appear only on admin responses.** Grep for it as well as
  testing it — the same shape as the driver-sees-no-customer-data assertion in
  spec 011

**Do not call Firebase Storage in tests.** Mock it. Follow the conftest spend
guard pattern, and remember that guard was broken for weeks because it patched
a `from`-imported name — patch through the module.

---

## Step 7 — Retention

Add a documented deletion path: when a driver account is closed, their
documents are deleted from Storage and their rows removed.

It does not need a scheduler in this spec. It needs to exist and be callable,
and `CLAUDE.md` needs to say why: under the DPDP Act personal data is retained
only for the purpose it was collected for, and indefinite storage is not a
lawful default.

---

## Deferred deliberately — add to `docs/future-plans.md`

**Aadhaar and identity verification.**

Not collected. Storing Aadhaar numbers or scanned copies places a private
entity under the Aadhaar Act and UIDAI's data security regulations —
masking obligations, purpose-specific consent in the driver's language,
enforced retention limits, a Grievance Officer, and breach reporting to UIDAI
alongside the Data Protection Board and CERT-In. The lawful route is
authentication rather than collection: DigiLocker, or eKYC through a licensed
AUA/KUA. Third-party shortcuts have been actively blocked.

Licence and RC prove what actually matters for goods delivery — that the
person may drive and the vehicle is theirs. Aadhaar proves neither.

Trigger: a registered business entity, a published privacy policy, and a
DigiLocker or licensed-intermediary pathway. Legal advice before any of it.

**Admin authentication.** The shared-secret review token has no audit trail
and cannot be revoked per person. Trigger: a second person reviewing
documents, or the React dashboard, whichever comes first.

---

## Step 8 — Update `CLAUDE.md`

The verification state machine, that `is_verified` is now derived rather than
set at registration, the Storage path convention and that client access is
denied, the signed-URL expiry, the interim admin token and its weakness, the
retention obligation and why it exists, and that Aadhaar is deliberately not
collected with a pointer to future-plans.

---

## Step 9 — Report and stop

1. The step 0 answers
2. Files created and edited, migration revision id
3. The Storage rules you wrote
4. Size cap and signed-URL expiry chosen, with reasoning
5. Test results, and a mutation check that removing the `is_verified` gate
   fails a test
6. Whether anything needs doing in the Firebase console that you could not do
7. Anything you were tempted to build and did not

Do not push. Do not build an admin UI.
