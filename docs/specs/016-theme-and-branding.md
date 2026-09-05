# Spec 016 — Theme, logo and splash

Build mode. Visual only. No behaviour changes, no new screens, no flow changes.

**Precondition:** spec 014 merged and verified in production. Both apps run on
device.

**Context:** the apps are being shown to friends tomorrow. This spec makes them
look like a product rather than a prototype. It is a baseline, not a final
design — the point is that the next iteration starts from something coherent
instead of Flutter defaults.

---

## New concepts introduced here

1. **A design system is data, not decoration.** Colours, spacing and type
   sizes become named tokens in one file. A screen never writes `#F5B400` or
   `padding: 16`; it references the token. That is what makes the second
   iteration cheap.
2. **A logo and an app icon are different artifacts.** The logo carries
   detail; the icon must survive being 48dp in a launcher grid. One is not a
   resized version of the other.
3. **Native splash is not a Flutter screen.** The splash shown before Flutter
   boots is an Android resource. It cannot be a widget, which is why it needs
   generated native assets rather than Dart.

---

## Guardrails

- **Do NOT change any layout, copy, flow, or navigation.** Colours,
  typography, spacing, corner radius, elevation, logo and splash only.
- **Do NOT redesign screens.** If a screen looks wrong after theming, report
  it — do not restructure it.
- **Do NOT touch the backend.**
- **Do NOT use `google_fonts`' runtime fetch.** It downloads the font on first
  use. VOLT is used in the field on patchy connections, and a delivery app
  that renders wrong until it has network is a bad trade for a typeface.
  Bundle a font as an asset or use the platform font.
- **Do NOT build a dark theme.** Deliberately deferred — see the end of this
  spec.
- Two build-time dependencies are permitted, named in step 4. Nothing else.
- Work on a branch: `feat/theme-and-branding`. Tell me before pushing.

---

## Decisions already made — implement, do not re-litigate

| Decision | Value |
|---|---|
| Direction | Navy and electric amber, taken from the logo |
| Brightness | **Light**. Dark is a future-plans item, not this spec |
| Scope | Both apps, via `volt_core`. One theme, not two |
| Primary action | Amber fill, navy label. Never amber with white text |
| Amber's role | Primary actions and highlights only. **Not** the warning colour |

---

## Step 0 — Inventory before changing anything

Before writing the theme, find every place that hardcodes a colour and will
therefore ignore it.

```
grep -rn "Colors\.\(white\|black\|grey\|gray\|blue\|amber\)" customer_app/lib driver_app/lib packages/volt_core/lib
grep -rn "Color(0x" customer_app/lib driver_app/lib packages/volt_core/lib
grep -rn "backgroundColor\|foregroundColor" customer_app/lib driver_app/lib packages/volt_core/lib
```

**Report the list before proceeding.** Each hit is either a token that should
move into `AppColors`, or a deliberate exception that needs a comment saying
why. If there are more than about twenty, say so — that changes the shape of
this spec and I would rather know than have you work around it.

Also report: what the current theme actually is — light or dark, and what the
existing palette contains.

---

## Step 1 — Branch

```powershell
cd $env:USERPROFILE\projects\volt
git checkout -b feat/theme-and-branding
```

---

## Step 2 — `packages/volt_core/lib/src/theme/app_colors.dart`

Replace the existing palette. Values are sampled from the logo. Adjust only if
something is demonstrably unreadable on device, and say what changed and why.

```dart
// Base — off-white rather than pure #FFF. Pure white glares outdoors, which
// matters because drivers use this in daylight.
static const background      = Color(0xFFFAFAFB);
static const surface         = Color(0xFFFFFFFF);
static const surfaceSunken   = Color(0xFFF1F2F4);
static const border          = Color(0xFFE2E4E8);

// Brand navy — from the logo. Headers, body text, secondary actions.
static const navy            = Color(0xFF1B2A4A);
static const navyDeep        = Color(0xFF16233F);

// Electric amber — from the logo. Primary actions and highlights.
static const primary         = Color(0xFFF5B400);
static const primaryPressed  = Color(0xFFD99F00);
// Text and icons placed ON amber. Navy, never white — amber with white text
// fails contrast badly and is the most likely mistake in this palette.
static const onPrimary       = Color(0xFF16233F);

// Text
static const textPrimary     = Color(0xFF16233F);
static const textSecondary   = Color(0xFF5A6376);
static const textDisabled    = Color(0xFF9AA1AF);

// Status — warning is orange, deliberately distinct from the amber used for
// primary actions, so a warning cannot read as a button.
static const success         = Color(0xFF1B9E4B);
static const warning         = Color(0xFFE8730A);
static const error           = Color(0xFFD32F2F);
```

**The contrast rule to hold to:** navy on light is strong, navy on amber is
strong, white on amber is unreadable. If you find yourself needing white text
on amber, that is the signal to use navy instead — not to lighten the text.

---

## Step 3 — `packages/volt_core/lib/src/theme/app_theme.dart`

Build a `ThemeData` with `brightness: Brightness.light` and a `ColorScheme`
from the tokens above. Cover, at minimum:

- `scaffoldBackgroundColor`, `cardTheme`, `dividerTheme`
- `elevatedButtonTheme` — amber fill, navy label, 12px radius, a real pressed
  state, and a disabled state that is visibly disabled rather than just faded
- `outlinedButtonTheme` — navy outline, navy label
- `textButtonTheme`
- `inputDecorationTheme` — filled with `surfaceSunken`, navy focus border,
  error border in `error`. Address entry is the most-used input in the app; it
  should feel deliberate
- `appBarTheme` — navy background, white foreground, no elevation. This is the
  one place white-on-navy is correct
- `snackBarTheme`
- `textTheme` — a real scale, not defaults

Also add a spacing scale as constants (4, 8, 12, 16, 24, 32) and a radius
scale (8, 12, 16). Screens reference these rather than raw numbers.

**Typography:** use the platform font unless you bundle one as an asset. If
you bundle, say which and why, and confirm the licence permits
redistribution. A well-set default beats a badly-set custom face.

---

## Step 4 — Launcher icon and splash

Two build-time dependencies. Both generate native assets at build time and
ship no runtime code:

- **`flutter_launcher_icons`** — generates Android launcher icons at every
  density plus the adaptive-icon layers. Replaces doing it by hand across six
  drawable folders.
- **`flutter_native_splash`** — generates the native splash resources.
  Replaces hand-editing `styles.xml` and a drawable per density.

Both go under `dev_dependencies`.

### The logo

A logo exists: vehicles and a city skyline behind a lightning icon, with the VOLT
wordmark and the tagline "QUICKER. SMARTER. DELIVERED." Ask me for the file
and confirm where to put it before assuming a path. Store it under
`packages/volt_core/assets/` so both apps share one copy.

**Splash** — use the full logo, centred, on `background`. It has room to
breathe there and the detail is legible.

**Launcher icon** — do **not** use the full logo. At 48dp the vehicles,
skyline and tagline become illegible. Use the **lightning icon** alone: amber lightning icon on
navy, filling the icon's safe zone. It is the strongest element in the mark
and the only one that survives scaling.

If extracting a clean lightning icon from the raster logo is not possible at sufficient
resolution, draw a matching one as vector and say that you did — do not ship a
blurry crop.

**Two apps, one phone.** The icons must be distinguishable. Suggestion: invert
the driver app's — navy lightning icon on amber — so they read as siblings rather than
duplicates. Propose an alternative if you have a better one.

Also configure the Android 12+ splash API, not just the legacy path.

---

## Step 5 — Fix the fallout from step 0

Work through the inventory. Each hardcoded colour becomes a token reference or
gains a comment explaining the exception.

**Do not change layout while you are in these files.** If a screen needs
structural work, note it for the report.

---

## Step 6 — Verify on device

`flutter analyze` proves nothing here. Both apps, real device, every screen:

| Screen | Check |
|---|---|
| Splash | Correct colour, no white flash before or after, logo not stretched |
| Launcher | Both icons present, distinguishable, legible at actual size |
| Phone entry | Input readable, keyboard doesn't hide the button |
| OTP | Code digits legible, resend link visible |
| Home / address entry | Autocomplete list readable, map controls visible |
| Vehicle selection | Selected state obvious at a glance |
| Booking status | Timeline steps distinguishable — done, current, upcoming |
| Driver card | Vehicle number is the most prominent element |
| Terminal states | Delivered, cancelled and expired each read differently |
| Driver: registration | Dropdown readable |
| Driver: job board | Fare prominent, cards scannable |
| Driver: active job | Primary action unmistakable one-handed |
| Error states | Turn WiFi off — error text and Retry both visible |

**Easy to miss:** any dialog or bottom sheet still rendering with default
Material colours, and the app name under the icon in the launcher.

---

## Deferred deliberately — add to `docs/future-plans.md`

**Dark theme.** Light ships first because it matches the logo, reads in
daylight, and is one theme rather than two. A dark variant is a real want —
drivers work at night, and an amber-on-navy dark theme is closer to the logo's
own character than this light one is.

Trigger: after the first real driver feedback, or when night bookings are a
meaningful share of volume.

Size: mostly a second `ColorScheme`, provided step 5 leaves no hardcoded
colours behind. That is the main reason step 5 matters beyond tidiness.

---

## Step 7 — Update `CLAUDE.md`

The palette and where it lives, the rule that screens use tokens rather than
raw values, that the theme is light-only by decision with dark deferred, that
amber is reserved for primary actions and never for warnings, that amber never
carries white text, and the two dev dependencies with what they generate.

---

## Step 8 — Report and stop

1. The step 0 inventory, and how many hits needed changing
2. Files created and edited
3. The step 6 table with real results — be explicit about anything not
   verified on device rather than implying it was
4. Any screen that looked wrong after theming and needs structural work,
   which you did not do
5. How the launcher icon was produced, and whether the lightning icon was extracted or
   redrawn
6. Anything you were tempted to redesign and did not

Do not push.
