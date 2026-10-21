<!--
main auto-deploys to production, migrations included, about two minutes after
merge. There is no staging. So this template is not paperwork — it is the only
thing between a merge and production.

docs/collaboration.md has the working agreement.
-->

## Spec

<!-- Which numbered spec does this implement? Link docs/specs/NNN-*.md.
     No spec? Say why — a bug fix or a doc change is a fine answer. -->

Implements: `docs/specs/`

## What it does

<!-- Two or three sentences. What changed and why, not a file list. -->

---

## Verified on a device

<!-- A human ran this on a real phone. Tests and `flutter analyze` are not
     device verification — spec 017 was green and fully analyzed while being
     unreachable from the app.

     List what you ACTUALLY exercised. Specifics: which screen, which flow,
     which backend. "Tested it" is not an entry. -->

- [ ] Ran on a real device (`RMX3371` or your own — say which)
- [ ] Against: local backend / deployed backend (delete one)

Exercised:

-

**NOT verified, and why:**

<!-- This section is the point of the whole template. Everything unproven,
     stated plainly. "Nothing" is only true if you really did walk every path
     this touches, including the failure ones.

     The honest answers that have mattered here: negative cases skipped,
     one app checked but not the other, happy path only, a path that needs a
     real driver or a real payment. -->

-

---

## Locked decisions

<!-- CLAUDE.md has a list of decisions not to be revisited without a strong
     reason — money in paise, per-audience response schemas, the atomic claim,
     404-not-403 on another user's booking, server-authoritative fares, the
     Riverpod mutation rule, and the rest.

     They look arbitrary until you know what went wrong to produce them. If
     this PR touches one, say which and what the argument is. If it does not,
     say so — that is a real answer, not a formality. -->

- [ ] This PR touches none of them
- [ ] It touches one or more — named below, with the argument

Touched:

-

## Future-plans triggers

<!-- docs/future-plans.md holds deferred decisions, each with an observable
     trigger. The failure mode is the trigger passing unnoticed. Did this
     work fire one? (e.g. a second instance → the rate limiter must move to
     Redis; a second document reviewer → §14 admin auth.) -->

-

---

## Console changes made outside git

<!-- LOAD-BEARING. Several of this project's hardest bugs were console state
     that no diff could show: Storage rules never applied, an API key
     restriction that blocks a browser fallback, an SMS region policy, a quota
     cap, a rotated service account key that silently kept verifying tokens
     while failing to sign anything.

     Anything changed in the Firebase console, Google Cloud console or the
     Render dashboard goes here — including anything the OTHER person must
     also set, like a new environment variable. A new required env var that is
     not written down here fails the deploy, or worse, half-succeeds.

     "None" is a valid and welcome answer. Leaving it blank is not. -->

-

## Migrations

- [ ] No migration in this PR
- [ ] There is one — round-tripped `upgrade`, `downgrade -1`, `upgrade`

<!-- The round-trip is not optional. A migration can read perfectly and still
     fail: op.add_column with sa.Enum does not emit CREATE TYPE on Postgres,
     and a generated downgrade drops the column but leaves the type behind.
     Both were only ever caught by running it.

     Remember the other person's local schema drifts the moment this merges. -->

## Dependencies

<!-- Any new one: what it does and what it replaces. "Replaces nothing" is a
     fine answer; an unexplained dependency is not. -->

-

---

## Checks

- [ ] `pytest` passes (say the count)
- [ ] `flutter analyze` clean on every package touched
- [ ] `flutter test` passes
- [ ] Branch is current with `main`
- [ ] No secret in the diff — no key, token, `.env`, or service account JSON

## For the reviewer

<!-- Not a formal review. The bar is "someone else has seen this ship."
     Worth a second pair of eyes on: anything under NOT verified, anything
     touching a locked decision, and every console change — because that last
     one is the part you cannot check by reading the diff. -->

-
