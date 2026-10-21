# VOLT — Working together

Two people now. This file is the working agreement. Read it before your first
commit.

---

## The one thing that will bite you

**`main` auto-deploys to production.** Push to `main` and it is live in about
two minutes, migrations included. With one person that was fine. With two it
means someone can ship something the other has never seen.

So: **nothing reaches `main` except through a pull request.**

---

## Branching

- One branch per spec: `feat/<short-name>`, matching the spec number's topic
- Open a PR into `main` when the spec's work is done and device-verified
- The other person reads it before it merges. Not a formal review — just
  "someone else has seen this ship"
- Delete the branch after merge

Rebase or merge `main` into your branch regularly. A branch that sits for two
weeks is a conflict waiting to happen, and the Flutter files are the worst
ones to resolve by hand.

---

## Who owns what

Four surfaces. **One person owns a surface for the duration of a spec.** Not
forever — per spec.

| Surface | Path |
|---|---|
| Backend | `volt-backend/` |
| Customer app | `customer_app/` |
| Driver app | `driver_app/` |
| Shared Dart | `packages/volt_core/` |
| Admin dashboard | not built yet |

If a spec needs both backend and app — most do — one person takes the whole
spec rather than splitting it down the middle. Splitting a spec across two
people means coordinating on an API contract that is still being designed,
which costs more than it saves at this size.

**`packages/volt_core/` is shared by both apps.** Changing it affects work the
other person may be doing right now. Say so before you touch it.

---

## The files that will conflict

**`CLAUDE.md`** is edited by almost every spec, so it conflicts constantly.
Two habits that help:

- Append to the end of the relevant section rather than rewriting it
- Update it in its own commit at the end of a spec, not scattered through

**`docs/specs/NNN-*.md`** — the numbers collide. Two people both writing
`018-` is a guaranteed conflict and, worse, two different specs with the same
number in each person's history.

**Claim the number first — in a PR title or a GitHub issue, not in the
repo.** "018 — driver ratings" as an issue or a draft PR title is the claim,
and it is visible to the other person before either of you has written a line.

Deliberately NOT a stub file on `main`. Two reasons, and the second is the
one that matters: a title-only file would have to reach `main` to be the
claim, which means pushing straight past the pull request rule above; and
`docs/specs/` means *decisions already made and implemented* (see
`CLAUDE.md`). Filling it with placeholders for work nobody has started erodes
the only thing that makes the three-way docs split useful — knowing what kind
of thing you are reading before you read it.

---

## Specs still come first

Unchanged, and it matters more now, not less:

1. The decision is debated and written as a numbered spec in `docs/specs/`
2. The spec is committed **before** implementation starts
3. It is handed to Claude Code with explicit guardrails
4. Claude Code shows its plan before writing code
5. Device verification is done by a human, and the results go in the report

A spec written down is how the other person understands work they were not
part of. That was always the point; now there is a second reader.

---

## Locked decisions

`CLAUDE.md` has a list of decisions that are not to be revisited without a
strong reason. They each have a cost attached to changing them, and the
reasoning is written next to each one.

The natural instinct of an engineer new to a codebase is to improve it.
**Read that list before improving anything.** If something on it looks wrong,
raise it — do not quietly change it. Several of those decisions look arbitrary
until you know what went wrong to produce them.

The same applies to `docs/future-plans.md`: those are deliberate deferrals
with triggers attached, not oversights.

**One of those triggers fires the moment this document becomes true.**
future-plans §14 (admin review token to real admin authentication) triggers on
"a second person reviewing documents, or the React dashboard, whichever comes
first." `ADMIN_REVIEW_TOKEN` is a single shared secret: there is no audit
trail, every approval is "whoever had the token", and `reviewed_by` is a
string the caller supplies rather than an identity.

With one reviewer that was merely weak. With two it is **retroactive** — the
second a second person approves a driver, every approval ever made becomes
unattributable, including the ones already in the database. Approvals do not
become attributable later. These endpoints are what let an unverified driver
carry someone's goods, so if document review is about to become a two-person
job, do §14 first.

---

## Secrets

Unchanged and absolute: **secrets never leave the machine they are used on.**
Not chat, not screenshots, not a scratch file. A service account key was
pasted once and had to be rotated.

Each person:

- Generates their **own** Firebase service account key. Do not share one.
  Firebase Console → Settings → Service accounts → Generate new private key →
  save as `volt-backend/secrets/firebase-service-account.json` (gitignored)
- Gets their **own** Firebase test phone number. Console → Authentication →
  Sign-in method → Phone → Phone numbers for testing. Sharing one means
  fighting over the same account mid-test
- Keeps their own `volt-backend/.env`, built from `.env.example`

The values that are genuinely shared — the Google Maps key, the admin review
token — are passed person to person, not committed and not pasted into a chat
with an AI.

**Label every service account key with its owner in the Google Cloud console,
and never delete a key you did not create.** Two people each holding their own
key means the console lists keys that look interchangeable and are not.

This is not hypothetical. On 8 Oct 2026 a key was rotated and the old one
deleted; the local key stopped working and **nothing looked broken**. Firebase
token verification does not use the private key — it checks Google's published
public certs — so auth kept working, every endpoint kept working, and the
whole test suite stayed green on a dead key. What silently stopped was
anything that *signs*: Firebase Storage uploads and signed URLs, which is all
of driver document verification. It was found days later by someone trying to
mint a test token.

So a key you delete does not fail loudly for its owner. It fails in one
feature, later, for reasons that do not point at you.

---

## Production is shared

One backend, one database, one Firebase project. There is no staging.

That means:

- `./run-local.ps1` for anything experimental. `./run-prod.ps1` writes real
  rows to the real database
- Say in chat before you run migrations against production, because the other
  person's local schema will drift
- Say before you change anything in the Firebase or Render consoles. Console
  changes are invisible in git, and several of this project's hardest bugs
  came from exactly that gap

---

## Onboarding checklist

For whoever is joining:

1. Clone the repo
2. Read `CLAUDE.md` end to end, then `docs/VOLT-handoff.md`, then
   `docs/future-plans.md`
3. Skim `docs/specs/` — at minimum 003 (schema), 008 (driver endpoints) and
   014 (road distance), since those carry the most reasoning
4. Generate your own service account key
5. Copy `.env.example` to `.env` and fill it in
6. Add your own Firebase test number
7. Set `VOLT_DEVICE` and `VOLT_LAN_IP`, then run the backend locally, run both
   apps against it, and make one booking end to end.

   The run scripts read both from the environment — they used to hardcode one
   person's phone and one person's LAN IP, so all four failed for anybody
   else. `flutter devices` gives the device id; `ipconfig` gives the IPv4 of
   the machine running the backend, which must be started with
   `--host 0.0.0.0` or the phone cannot reach it.

   ```powershell
   $env:VOLT_DEVICE = 'RMX3371'
   $env:VOLT_LAN_IP = '192.168.1.8'
   ```

   Unset, the scripts stop with a message saying which one is missing rather
   than failing somewhere inside Flutter. To keep them across terminals:
   `[Environment]::SetEnvironmentVariable('VOLT_LAN_IP','192.168.1.8','User')`
8. **Write down everything in the docs that did not make sense.** That list is
   the most valuable thing a new reader produces, and it expires within a
   week

Step 8 is not a courtesy. Docs written by the person who built the thing have
blind spots that only a second reader can find.

---

## When you disagree

Write it down rather than arguing in chat. A one-paragraph note in the spec
saying "we considered X and chose Y because Z" is worth more in three months
than whoever won the argument.

The project's own history is the argument for this: the decisions that have
held up are the ones with a reason recorded next to them.
