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
