# VOLT — Future plans

Decisions that are **correct now and wrong at scale**, with the trigger that
says when to change them.

## What belongs here

A section in this file is a decision that was made deliberately, is right for
today's size, and has a known replacement waiting on a condition that has not
happened yet. The point of writing it down is the **trigger**: without one, the
condition passes unnoticed and the decision quietly becomes a defect.

Where it sits relative to the other documents:

| Document | Holds |
|---|---|
| `../CLAUDE.md` | Conventions, and the current state as it actually is |
| `specs/` | Decisions already made **and implemented**, each recording *why* |
| `VOLT-handoff.md` | Today's status — what is in flight, blocked, next |
| **this file** | Decisions deliberately **deferred**, each with a trigger |

A plan graduates out of this file by becoming a numbered spec in `specs/`. It
does not get deleted when it graduates — the spec supersedes it, and the entry
here should say so.

## What does not belong here

- Anything already implemented. That is a spec.
- Anything blocking work right now. That is the handoff.
- Technical detail that already lives in `../CLAUDE.md`. **Link to it instead.**
  Two copies of the same technical fact drift, and the copy someone reads is
  never the one that was updated.
- A vague concern with no observable trigger. "When we grow" is not a trigger;
  it is a way of never noticing.

## Conventions for an entry

Six fields, in this order, every time. Where something is genuinely not decided,
it says `TBD — owner decision` rather than a plausible-looking guess — an
invented trigger is worse than an absent one, because it looks like a decision
has been made.

---

## 1. Google Maps routing → self-hosted routing

**What we do today.** Google Routes API `computeRoutes` with `TRAFFIC_AWARE`,
called live on every fare estimate and again on every booking creation, with no
cache. This is deliberate on both counts: `TRAFFIC_AWARE` because traffic is
the dominant term in a Bengaluru ETA, and uncached because the licence forbids
it. See *Real road distance (spec 014)* in `../CLAUDE.md`, and `specs/014-real-road-distance.md`.

**Why it does not scale.** Three mechanisms, and the third is the one that
actually forces the migration rather than merely making it attractive:

1. *Cost is per call, with no hard ceiling.* Routes API quotas are all marked
   `Adjustable: No` and the per-day quota is `Unlimited`. The only limit is
   3,000 per minute, which bounds rate, not spend. See the spend-cap entry in
   `../CLAUDE.md` Known gaps.
2. *The obvious cost fix is unavailable.* Caching distance or duration is not
   permitted — Service Specific Terms s19 covers lat/lng only. So the usual
   answer to per-call pricing, cache the repeats, is closed to us by licence
   rather than by engineering.
3. *The terms prohibit using Google Maps Content to train, test, validate or
   fine-tune ML models.* This collides head-on with phase 6 of the roadmap —
   ETA prediction, demand forecasting, dynamic pricing. It is not a cost
   problem that can be deferred by spending more; it is a permission problem
   that makes an entire planned phase unbuildable on this data.

**What replaces it.** Self-hosted routing on OpenStreetMap data — OSRM or
Valhalla. Per-VM cost instead of per-call, cacheable without restriction, and
output we own outright, which is what unblocks phase 6. Worth pricing against
the managed Indian alternatives at the time rather than assuming self-hosting
wins: Ola Maps, MapmyIndia/Mappls.

**Trigger.** `TBD — owner decision`. Candidates under consideration: the
monthly Maps bill exceeding a threshold, or the start of phase 6 work,
whichever comes first.

**Rough size.** A spec. New service, new deployment target, and the fallback
behaviour has to be re-verified end to end — `distance_source` currently
distinguishes `google` from `haversine` and would need a third value.

**What waiting costs.** Nothing structural. But every month of phase 6
groundwork built on Google-derived distances is work that has to be redone on
owned data, because the terms do not permit that groundwork in the first place.
Waiting is free; *building phase 6 while waiting* is not.

---

## 2. Firebase phone OTP → domestic SMS provider

**What we do today.** Firebase Authentication phone OTP on the Blaze plan,
delivered by Google's own sender. Deliberate: it was the fastest route to real
auth, and it is genuinely working end to end in both apps. See *Auth* in
`../CLAUDE.md` and `specs/005-firebase-auth.md`.

**Why it does not scale.** Two mechanisms:

1. *Per-SMS cost.* **$0.07 for India** — Google Identity Platform pricing
   page, confirmed 5 Sep 2026. Roughly an order of magnitude above domestic
   Indian providers. Concretely: 10,000 verifications is **$700**, and that is
   one sign-in each, before re-auth on a new device or a resent OTP. Invisible
   at ten testers; a real line item the moment there is a real user base.

   The domestic side of that comparison is **not yet costed** — no provider
   quote is recorded here, so "an order of magnitude" is an estimate, not a
   measured saving. Getting one real DLT-registered provider's per-SMS rate is
   what turns the trigger below from a judgement call into arithmetic.
2. *The TRAI DLT registration is Google's, not ours.* Messages come from a
   Google-controlled sender, so we have no DLT registration of our own to
   produce if a carrier or an enterprise client asks for one. That is a
   compliance and credibility problem, not a cost one, and money does not fix
   it.

**What replaces it.** A DLT-registered Indian OTP provider for delivery, while
**keeping Firebase Auth for session and token management** — mint a Firebase
custom token from a provider-verified session. This is a swap of the delivery
channel, not of the auth model. `get_current_user` and the ID-token
verification on the backend are unaffected.

**Trigger.** `TBD — owner decision`.

**Rough size.** A spec. Touches auth in both apps and the backend's token
verification.

**What waiting costs.** Nothing. The swap sits behind the existing
`AuthRepository` interface, which is exactly what that interface was for.

---

## 3. Rate limiting → Redis

**What we do today.** An in-process fixed-window counter, per IP, on
`POST /bookings/estimate` only. Deliberate, and deliberately minimal: it is
the smallest thing that had to exist before spec 014 could merge, not the
rate-limiting spec. See *Rate limiting* in `../CLAUDE.md`.

**Why it does not scale.** The counter is a module-level dict in one Python
process. On N instances each keeps its own, so the effective limit becomes
20 × N. **Nothing raises, nothing logs, no test fails** — the only symptom is
a Google bill. Render's free plan being single-instance is the only reason the
current design is honest, which makes this a property of the hosting plan
rather than of the code.

**What replaces it.** A Redis-backed limiter, already anticipated as part of
the phase 3 Redis work.

**Trigger.** A second instance, or any move to a paid plan with autoscaling.
**This must happen in the same change, not after it** — the failure is silent,
so there is no moment at which someone notices it needs doing.

**Rough size.** Part of the phase 3 Redis work.

**What waiting costs.** Nothing while single-instance.

---

## 4. Google Cloud spend cap

**What we do today.** Alerts only: a ₹500 monthly budget with thresholds at
50/90/100%. Deliberate — see the spend-cap entry in `../CLAUDE.md` Known gaps
for why enforcement was not enabled.

**Why it is not enough.** Alerts fire *after* the money is spent; they notify,
they do not stop anything. Budget "Spend cap enforcement" does exist, but it is
in Preview, covers only a limited set of services which may not include Maps
Platform, and is scoped to **all projects and all services** — so enabling it
risks pausing Firebase auth and everything else rather than just Routes. A cap
that takes down phone login to save a Maps bill is worse than the bill.

**What replaces it.** Spend cap enforcement, scoped to Maps Platform.

**Trigger.** When spend cap enforcement leaves Preview **and** can be scoped to
a single service. Also re-check at free trial expiry — 3 Dec 2026 per
`../CLAUDE.md` — when the credit ceiling disappears and Blaze bills the card
directly for both Maps and Firebase SMS.

**Rough size.** A console change.

**What waiting costs.** Nothing today, but the exposure grows once the trial
credit is gone: until then the credit is itself a ceiling, and afterwards
nothing is.

---

## 5. SMS abuse protection → reCAPTCHA SMS defense

Important before any public release. Not urgent now, and the reason it is not
urgent is a fact about distribution rather than about the code.

**What we do today.** Not configured — the reCAPTCHA site keys do not exist.
Abuse protection is the SMS region policy alone (allowlist, India only, set
5 Sep 2026) plus the default 1000/day sent-SMS quota. See the SMS block under
*Auth* in `../CLAUDE.md` for the current settings.

**Why it does not scale.** The region policy and reCAPTCHA stop two different
attacks, and we only have the first:

- The region policy blocks foreign numbers, which kills SMS pumping — the
  revenue-share fraud where an attacker triggers OTPs to numbers they profit
  from. That attack is genuinely closed.
- It does **nothing** against a bot hammering *Indian* numbers. That is the
  attack that matters the moment the app is publicly installable, because
  every request is a legitimate-looking domestic verification.

At $0.07 per SMS (see §2 for the source) the default 1000/day quota is about
**$70/day**, roughly ₹6,000/day, of exposure. The quota bounds the damage; it
does not prevent it, and it is a daily bound rather than a total one.

**What replaces it.** reCAPTCHA SMS defense, alongside the region policy
rather than instead of it — that pairing is Google's own recommendation.

**Trigger.** Before public Play Store release. **Also immediately** if either
abuse signal appears:
- SMS volume that does not match the known tester list.
- Verification success rate below **75%** in any region — Google names that
  threshold as an abuse signal.

Both of those require §6 to exist first. Nothing currently watches SMS volume,
so today the second trigger cannot fire — which is the real argument for doing
§6 before it is needed rather than after.

**Rough size.** A spec, not a console change. Create reCAPTCHA site keys,
configure in Firebase, and note the floor: Android SDK **23.1.0 or later**,
which means checking and possibly bumping `firebase_auth` in BOTH Flutter apps.
Spec 013 is the precedent for why that is not free — adding one Firebase
package forced `firebase_core` up and broke `firebase_auth` compilation until
it moved too. Misconfiguration makes sign-in FAIL FOR REAL USERS, so this needs
on-device verification, not just a green analyzer.

**What waiting costs.** Nothing structural while distribution is sideloaded
APKs to known people. The cost arrives with public installability, not
gradually — which is why the trigger is an event and not a number.

---

## 6. SMS metrics monitoring

**What we do today.** Nothing watches SMS volume. Deliberate only in the sense
that there is nothing yet to watch — the tester list is short enough that
anomalies would be noticed by hand.

**Why it does not scale.** It is not a scaling problem so much as a blind spot
that becomes load-bearing: §5's abuse triggers are both defined in terms of
metrics nobody is collecting. An attack would be visible only in the bill,
after the fact.

**What replaces it.** Cloud Monitoring on the metrics Google documents for
this — sent SMS count, blocked SMS count, and phone verification count, each
carrying a region code. The usable rule those give:

> verification success rate = verification count ÷ sent count;
> **below 75% in a region suggests abuse.**

That ratio is the whole point of collecting all three rather than just volume:
a raw spike is ambiguous — a launch looks like an attack — but a spike with a
collapsing success rate is not.

**Trigger.** When real users exist beyond the tester list.

**Rough size.** Console setup, no code.

**What waiting costs.** `TBD — owner decision`. Not stated, and worth deciding
rather than assuming: the honest answer is probably "nothing, but it gates
§5's second trigger", which makes it cheap insurance rather than free.

---

## 7. Fare model: distance only → a time component

Moved here from `../CLAUDE.md` on 5 Sep 2026, along with §8 and §9. They were
recorded there as "planned, not built", which is this file's job.

**The common thread across §7, §8 and §9: VOLT prices geometry, not effort.**
Spec 014 made distance real, but distance is still the *only* thing a fare
depends on. Each of the three is a different consequence of that.

**What we do today.** `_fare_paise` takes `distance_m` and nothing else. A 6km
trip at 11pm and the same trip at 6pm cost the same, despite roughly triple the
driver's time. Deliberate — it was the simplest model that priced anything at
all — and now the largest known gap between what a fare charges and what a trip
costs the person driving it.

**Why it does not scale.** The mis-pricing is systematic, not random: it always
favours the customer on slow trips and always penalises the driver, and slow
trips are exactly the ones a driver can least afford to take. Ola, Uber and
Porter all price base + per-km + per-minute, which is the market telling us the
same thing. Note that spec 014 already fixed the *other* half of this — the
flat 1.4 multiplier mis-priced per route in both directions — so this is the
remaining term, not a repeat.

**What replaces it.** A `per_minute_paise` column on `vehicle_types`, with
duration taken from spec 014's `RouteResult`, which already arrives on every
call — so the input is free and needs no new API request.

**IMPORTANT: per-km must come DOWN when per-minute goes in, not stay put.**
Otherwise this is a second fare rise stacked on 014 rather than a
redistribution of the same fare toward the trips that actually cost more. That
distinction is the whole point, and it is the easiest thing to lose when the
change is finally made.

**Trigger.** `TBD — owner decision`.

**Rough size.** `TBD — owner decision`. What is known: a migration for the new
column, a change to `_fare_paise`, and no new data source. Both apps display
fares from the server, so neither should need changing.

**What waiting costs.** `TBD — owner decision`. Worth noting that fares are
snapshotted per booking, so no past booking is rewritten whenever this lands.

---

## 8. Waiting charges

**What we do today.** The time between `driver_assigned_at` and `picked_up_at`
is unpaid driver time. Nothing measures it and nothing charges for it.

**Why it does not scale.** Same thread as §7 — the driver absorbs the cost of
time. Industry norm is a free window of 15–25 minutes, then per-minute.

**What replaces it.** Per-minute charging after a free window. **No schema work
is needed:** `final_fare_paise` is already deliberately separate from
`quoted_fare_paise` for exactly this, and both timestamps are already recorded.

**Trigger.** `TBD — owner decision`. Dependency rather than trigger: it belongs
near phase 4 payments, since it is the first thing that makes the final fare
differ from the quote in a way a customer has to be shown and asked to pay.

**Rough size.** `TBD — owner decision`. Smaller than §7 — the data model
already anticipates it.

**What waiting costs.** `TBD — owner decision`.

---

## 9. Job board → proximity matching

Not a pricing change, despite sitting between two of them. Recorded here
because the *symptom* looks like pricing and the fix is not.

**What we do today.** The job board is city-wide: every online driver with a
matching vehicle type sees every unclaimed booking, first to accept wins. See
*Matching* in `../CLAUDE.md`.

**Why it does not scale.** A Whitefield driver sees a Koramangala pickup and
eats the approach unpaid. **That is the real reason a driver declines distant
jobs**, and it is worth naming precisely, because the obvious-looking fix is
the wrong one: nobody charges the customer for the approach. Adding an approach
fee would be solving a matching problem with pricing, and would make the
product worse in the process.

**What replaces it.** Matching by driver location.

**Trigger.** `TBD — owner decision`. Dependency rather than trigger: it needs
phase 3 live location tracking, which does not exist yet.

**Rough size.** `TBD — owner decision`.

**What waiting costs.** `TBD — owner decision`.

---

## 10. Lazy expiry → a scheduled sweep

Moved here from `../CLAUDE.md` Known gaps on 5 Sep 2026. It was labelled there
as "known debt — replace once there's real traffic to justify it", which is a
deferral without an observable trigger: exactly the shape this file exists to
give a trigger to.

**What we do today.** `expire_stale_bookings()` runs lazily at the top of three
read endpoints, throttled to at most once per 60s per process. Deliberate, and
it solved a real problem — polling had every open screen dragging a write
transaction behind every request. See *Expiry* in `../CLAUDE.md` for the
throttle and the partial index that serves its predicate.

**Why it does not scale.** The mechanism is that expiry is driven by *traffic*
rather than by *time*. The effective window is "5 minutes plus however long
until the next request", so with no traffic nothing expires at all. Already
observed in real data: three bookings created minutes apart came back with the
same `expired_at`, because nothing hit the API in between and one sweep caught
all three. It degrades in the quiet direction — the fewer users, the more wrong
the expiry time — which is the opposite of most scaling problems and easy to
misjudge.

**What replaces it.** A scheduled job running the same UPDATE on a timer,
independent of request traffic.

**Trigger.** `TBD — owner decision`. The existing wording, "once there's real
traffic to justify it", is not an observable condition — and note it points the
wrong way: more traffic makes lazy expiry *more* accurate, not less. A
defensible trigger would be about correctness rather than load, e.g. the first
time an expiry timestamp being late actually matters to a customer or a driver.

**Rough size.** `TBD — owner decision`. The query and its index already exist;
what is missing is somewhere to run it from, which Render's free plan does not
provide.

**What waiting costs.** `TBD — owner decision`. Nothing structural — the sweep
is idempotent and the throttle is per-process by design.

---

## 11. Light theme → a dark variant

Deferred by spec 016 itself rather than discovered later.

**What we do today.** One light theme, shared by both apps, in
`packages/volt_core/lib/src/theme/`. `MaterialApp` sets `theme` and no
`darkTheme`, so a phone in dark mode still gets the light one — deliberate,
not an omission. The native splash is light in both `values` and
`values-night`, for the same reason.

**Why it does not scale.** It is not a scaling problem, it is an unserved use
case: **drivers work at night.** A light app at 11pm on a bike is a worse tool
than a dark one, and the amber-on-navy of the logo is closer in character to a
dark theme than to the light one that ships. Light went first because it
matches the mark, reads in daylight, and is one theme rather than two.

**What replaces it.** A second `ColorScheme` plus a dark `ThemeData`, selected
by `themeMode`. Mostly mechanical — **provided no screen has its own opinion
about colour.** That is the real reason spec 016's step 5 mattered beyond
tidiness: every hardcoded `Colors.white` left behind is a pixel that ignores
the dark theme and has to be hunted down later. After 016 there is exactly one
left in app code, commented, and it is white-on-navy.

**Trigger.** After the first real driver feedback, or when night bookings are
a meaningful share of volume.

**Rough size.** Mostly a second `ColorScheme`. The larger unknown is not Dart:
the launcher icon and splash have `values-night` variants that currently
duplicate the light ones, and the adaptive icon background is a flat colour
per app.

**What waiting costs.** It grows with every screen added between now and then,
since each one is another chance to hardcode a colour. Cheap to hold at
today's screen count.

---

## 12. Storage bucket region: US-EAST1 → India

**What we do today.** The Firebase Storage default bucket
`volt-2b36f.firebasestorage.app` is in **US-EAST1**, production-mode rules,
enabled 6 Sep 2026 for spec 017. Deliberate and forced: Mumbai
(`asia-south1`) is not in the free tier.

**Why it does not scale.** Driver licences and vehicle RCs are personal data
belonging to Indian residents, and they will be sitting on servers in the
United States. Two separate problems:

1. *Legal.* This is the first data in VOLT with a retention obligation, and
   cross-border storage is the adjacent question. Nothing today forbids it,
   but a data-residency requirement is exactly the kind of thing that arrives
   as a notification rather than a negotiation. Do not take this paragraph as
   legal advice — the point of recording it is that the decision is already
   made and cannot be revised later without work.
2. *Latency.* Every upload from a driver's phone in Bengaluru crosses an
   ocean, and so does every signed-URL read during review. Not a today
   problem at one reviewer and a handful of drivers.

**THE LOCATION IS PERMANENT.** A bucket's location cannot be changed after
creation. This is not a setting to flip later; it is a new bucket.

**What replaces it.** A second bucket in `asia-south1`, plus a migration:
copy every object across, rewrite every `driver_documents.storage_path`, and
cut over. The `storage_path` column holds a path rather than a URL precisely
so that a bucket move rewrites one column and nothing else — see spec 017.

**Trigger.** An Indian data-residency requirement under the DPDP Act — a
government notification restricting transfers, or a client, insurer or
regulator who requires it in writing.

**Rough size.** A new bucket plus a migration. Small while the bucket holds a
dozen documents; it is the object copy that grows, not the code.

**What waiting costs.** It grows with every document uploaded, because the
migration is proportional to the number of objects. Cheap now, and it is the
one entry in this file where waiting has a strictly increasing price.

---

## 13. Aadhaar and identity verification

**NOT COLLECTED, and this is a decision rather than an omission.** Spec 017
collects a driving licence and a vehicle RC. There is no `aadhaar` value in
the `DocumentType` enum and a test asserts its absence, so adding one is a
deliberate act that fails the suite first.

**What we do today.** Licence and RC, reviewed by a human. They prove the two
things that actually matter for goods delivery: that the person may drive, and
that the vehicle is theirs.

**Why we do not go further.** Storing Aadhaar numbers or scanned copies places
a private entity under the Aadhaar Act and UIDAI's data security regulations —
masking obligations, purpose-specific consent in the driver's own language,
enforced retention limits, a Grievance Officer, and breach reporting to UIDAI
alongside the Data Protection Board and CERT-In. That is a compliance
programme, not a schema column.

The lawful route is **authentication rather than collection**: DigiLocker, or
eKYC through a licensed AUA/KUA. Third-party shortcuts offering Aadhaar
verification without that licensing have been actively blocked, which is
itself the signal.

And it would not buy what it looks like it buys. Aadhaar proves neither that
someone may drive nor that a vehicle is theirs.

**Trigger.** All three of: a registered business entity, a published privacy
policy, and a DigiLocker or licensed-intermediary pathway. Legal advice before
any of it — nothing in this file is legal advice.

**Rough size.** `TBD — owner decision`. It is an integration plus a compliance
posture, not a feature.

**What waiting costs.** Nothing. Manual review of a licence is slower per
driver and completely lawful.

---

## 14. Admin review token → real admin authentication

**What we do today.** The document review endpoints are protected by a single
shared secret in `ADMIN_REVIEW_TOKEN`, sent as `X-Admin-Token` and compared
with `hmac.compare_digest`. An unset token returns 503 rather than opening the
endpoints.

**Why it does not scale.** Three specific things, none of which matter at one
reviewer and all of which matter at two:

1. *No audit trail.* Every approval is "whoever had the token". `reviewed_by`
   is free text supplied by the caller, so it records a claim, not an identity.
   These endpoints can make an unverified driver able to carry goods.
2. *No per-person revocation.* Revoking for one person revokes for everyone,
   and needs a redeploy to rotate.
3. *No expiry*, and it sits in an environment variable on Render.

**What replaces it.** Real admin authentication with per-person identity, so
`reviewed_by` records who rather than what was claimed. Likely Firebase Auth
with a custom claim, reusing the token verification already in `app/auth.py`
rather than inventing a second auth model.

**Trigger.** A second person reviewing documents, or the React dashboard —
whichever comes first. The first is the sharper one: the moment two people
share this token, the audit trail is not weak, it is absent.

**Rough size.** `TBD — owner decision`. Smaller than it sounds if it reuses
Firebase: an admin claim, a dependency alongside `get_current_driver`, and a
real `reviewed_by`.

**What waiting costs.** Nothing structural. But every approval made under the
shared token is an unattributable record, and those do not become attributable
later.
