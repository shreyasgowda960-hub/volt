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

**Claim the number first.** Create the file with just a title and push it
before writing the body. The file existing on `main` is the claim.

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

**Delete old service account keys** in Google Cloud IAM when you rotate. An
active forgotten key is worse than a revoked one.

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
7. Run the backend locally, run both apps against it, make one booking end to
   end
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
