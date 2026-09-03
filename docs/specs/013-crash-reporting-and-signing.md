# Spec 013 — Crash reporting and release signing

Build mode. Infrastructure, not features. Nothing user-visible changes.

> ## STATUS: Part A done, Part B DEFERRED — not forgotten
>
> **Part A (Crashlytics) is implemented and merged.** See the delta notes at
> the bottom of this file for what differed from the text below.
>
> **Part B (release signing) is deliberately deferred** until we are actually
> preparing a Play Store upload. The reasoning:
>
> - The upload key is **permanent in effect**. Android only installs updates
>   signed by the same key, so the sensible time to create one is when there
>   is a real upload to make and the whole flow — keystore, Play App Signing,
>   the third fingerprint Google's app-signing key adds — can be done and
>   verified in one sitting. Generating it months early means a key and a
>   password to look after with nothing yet depending on them.
> - Nothing is blocked by waiting. Sideloaded debug-signed APKs install and
>   run fine for testing with friends, which is the only distribution
>   happening today.
> - B6 is the trap that makes half-doing this worse than not starting: a
>   release build signed with a new upload key has a **different SHA-1**, and
>   phone auth silently fails until that fingerprint is added to Firebase.
>   Set up and left untested, it would look done and break the moment it
>   mattered.
>
> The consequence is recorded in `CLAUDE.md` under Known gaps: release APKs
> for both apps are debug-signed and cannot go to the Play Store. That entry
> is the reminder — this note exists so the empty Part B below does not read
> as an oversight.

**Note on numbering:** this takes 013. Distance Matrix moves to **014**.
`CLAUDE.md` references 013 as Distance Matrix — correct it.

**Precondition:** spec 012 merged and deployed. Both apps working against
production.

## Why now rather than later

Two things that only get worse with time.

**You have no crash reporting.** If either app crashes on someone else's phone,
you learn about it if they mention it. No stack trace, no device, no count, no
idea which build. Every bug report is currently "it stopped working."

**Your release APKs are debug-signed.** They cannot go to Play Store, and more
importantly the signing key you eventually publish with is permanent — Android
only installs updates signed by the same key. Setting this up before there are
users means a mistake costs nothing.

## New concepts introduced here

1. **Upload key vs app signing key.** With Play App Signing, Google holds the
   key that actually signs what users install. You hold an *upload* key, used
   only to prove uploads are from you. Lose it and Google resets it. Without
   this, losing your key means never updating your app again — new package
   name, new listing, zero installs carried over.
2. **Obfuscation breaks stack traces.** Release builds can rename symbols to
   make reverse engineering harder — which turns every Crashlytics report into
   unreadable noise unless the debug symbols are uploaded alongside. These two
   features have to be set up together or the second silently ruins the first.
3. **Crash reports carry PII by default.** A stack trace can include the values
   that caused it. A logistics app has phone numbers and home addresses in
   scope, so what gets attached is a deliberate decision, not a default.
4. **Zone errors.** Flutter has several error paths — framework errors, async
   errors outside the framework, and native crashes. Each needs wiring
   separately or a whole category goes unreported.

## Guardrails

- **Do NOT add analytics.** Crash reporting only. Analytics is a separate
  decision with its own consent implications.
- **Never attach phone numbers, addresses, or names to a crash report.**
  Firebase uid only.
- **Do NOT commit the keystore or its passwords.** Ever, on any branch.
- **Do NOT publish to Play Store in this spec.** Setup only.
- Branch. Tell me before pushing.

---

# PART A — Crashlytics

## A1. Enable in Firebase

Firebase console → Volt project → Build → **Crashlytics** → Get started.

It will ask you to add the SDK; that is the next step.

## A2. Add to both apps

```powershell
cd customer_app
flutter pub add firebase_crashlytics
```

Same for `driver_app`.

**`firebase_crashlytics`** — captures Dart and native crashes, uploads them
with device and OS context. Replaces nothing.

Android setup needs the Crashlytics Gradle plugin. **Read the package's current
README from the pub cache** rather than writing the Gradle changes from memory.

## A3. Wire every error path

In each app's `main.dart`, after `Firebase.initializeApp`:

- `FlutterError.onError` → Crashlytics, for framework errors
- `PlatformDispatcher.instance.onError` → Crashlytics, for uncaught async
  errors that never reach the framework
- Native crashes are automatic once the plugin is installed

Verify all three are covered against the current package docs. Missing
`PlatformDispatcher.instance.onError` is the common gap, and async errors are
where most real crashes live.

**Only in release builds.** In debug, errors should keep going to the console
where you can see them — a crash silently uploaded instead of printed is worse
for development. Use `kDebugMode` to gate it, and say so in a comment.

## A4. Identify users without identifying them

```dart
FirebaseCrashlytics.instance.setUserIdentifier(uid);
```

Firebase uid only. **Not phone, not name, not address.**

The uid lets you see "this crash hit 3 users, one of them 5 times," which is
what you need to triage. Cross-referencing to a person is possible through your
own database when genuinely required, which is the right amount of friction.

Set it on sign-in, clear it on sign-out.

Add custom keys that help triage and carry no PII: `apiBaseUrl` (which backend),
`bookingStatus` where relevant, and the app flavour. Do **not** add booking
codes — they resolve to an address.

## A5. Force a test crash

Add a temporary, debug-only button that calls
`FirebaseCrashlytics.instance.crash()`.

**A crash reporter you have never seen fire is not a crash reporter.** Trigger
it on a release build, confirm the report appears in the console with a
readable stack trace, then delete the button.

Crashlytics can take several minutes to show the first report of a new app.

---

# PART B — Release signing

## B1. Generate the upload key

```powershell
cd $env:USERPROFILE
keytool -genkey -v -keystore volt-upload-key.jks -keyalg RSA -keysize 2048 -validity 10000 -alias volt-upload
```

`keytool` comes with the JDK — `C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe`
if it is not on PATH.

It asks for a keystore password, a key password, and identity details. Use a
real password and **write it down somewhere you will still have in five years**.

**Where to put the file:** NOT inside the repo. Somewhere like
`C:\Users\admin\keys\volt-upload-key.jks`.

**Back it up now, not later.** Encrypted cloud storage, or a password manager
that takes file attachments. Losing this is recoverable under Play App Signing
— Google can reset an upload key — but recovery takes days and a support
request, and there is no reason to need it.

## B2. Wire it into Gradle

**New file: `customer_app/android/key.properties`** — gitignored:

```
storePassword=<yours>
keyPassword=<yours>
keyAlias=volt-upload
storeFile=C:/Users/admin/keys/volt-upload-key.jks
```

Forward slashes even on Windows; Gradle parses this as a properties file.

Add to the repo-root `.gitignore`:
```
**/key.properties
*.jks
*.keystore
```

Then a `signingConfigs` block in `android/app/build.gradle.kts` reading that
file, with `buildTypes.release` using it. **The build must fail clearly if
`key.properties` is missing** — a teammate cloning the repo should get "no
key.properties" rather than a release build silently falling back to the debug
key, which is exactly the situation you are in now.

Same for `driver_app`. **Same keystore, different alias is unnecessary** — one
keystore can sign both apps, and they are separate Play listings regardless.

## B3. Obfuscation, and the trap

```powershell
flutter build appbundle --release --obfuscate --split-debug-info=build/symbols --dart-define=API_BASE_URL=https://volt-api-951s.onrender.com
```

`--obfuscate` renames Dart symbols. **Every Crashlytics stack trace then
becomes unreadable** unless the files in `build/symbols` are uploaded.

Two options, and pick deliberately:

- **Skip obfuscation for now.** Readable crash reports, slightly easier
  reverse engineering of an app whose secrets are all server-side anyway.
- **Obfuscate and upload symbols** on every release build, and never lose a
  symbols directory, because a trace without its matching symbols is
  permanently unreadable.

**Recommend skipping obfuscation until there is a reason.** Your fare logic,
auth, and keys are all server-side — there is little in the APK worth hiding,
and readable crashes are worth more right now. Note the decision in
`CLAUDE.md`.

## B4. App bundle, not APK

Play Store takes `.aab`, not `.apk`:

```powershell
flutter build appbundle --release --dart-define=API_BASE_URL=https://volt-api-951s.onrender.com
```

Keep building APKs for sideloading to friends. Both work; they are different
artifacts for different distribution paths.

## B5. Verify the signature

Confirm the release build is actually signed with the upload key and not
falling back to debug:

```powershell
keytool -printcert -jarfile build\app\outputs\bundle\release\app-release.aab
```

The SHA-1 must **not** be `3F:45:C2:...` — that is the debug key. If it is, the
signing config is not being applied.

## B6. The new SHA-1 must go into Firebase

A release build signed with the upload key has a **different SHA-1**, and
Firebase phone auth checks fingerprints per app.

Get it from B5, then Firebase console → Project settings → each Android app →
Add fingerprint.

**Without this, phone auth fails in release builds while working perfectly in
debug** — a classic and confusing bug, because everything works on your machine.

Note also: once Play App Signing is enabled at upload time, Google's *app
signing* key produces a third fingerprint, which also needs adding. That
happens when you first upload, not now.

## B7. Build scripts

`customer_app/build-release.ps1` and the same for `driver_app`, wrapping the
appbundle command with the production URL. Commit them.

---

## Step C — Verify

| Test | Expected |
|---|---|
| `keytool -printcert` on the bundle | SHA-1 is the upload key, not debug |
| Release APK installs and runs | Works |
| Phone sign-in on the release build | Works — proves B6 |
| Test crash button, release build | Report in Crashlytics within minutes |
| Report shows a readable stack trace | Yes |
| Report shows the Firebase uid | Yes, and no phone number anywhere |
| Delete the crash button, rebuild | Still works |

The PII check matters. Open the report and look at every field — user
identifier, custom keys, logs. A phone number appearing anywhere means A4 is
wrong.

## Step D — Update `CLAUDE.md`

Crashlytics in both apps and that it is release-only; uid-not-phone and why;
the keystore location and that it is backed up (not the passwords); the
obfuscation decision; that release builds need their SHA-1 in Firebase; and
that spec 014 is Distance Matrix.

## Step E — Report and stop

1. Files created and edited across both apps
2. The step C table with real results
3. The upload key's SHA-1, so I can add it to Firebase
4. Whether the build fails cleanly without `key.properties`
5. Anything in the Crashlytics or Gradle docs that differed from this spec

Do not publish to Play Store. Do not push.

---

# What actually shipped — Part A deltas

## Two deviations from A3 and A5, both approved before implementing

**1. `setCrashlyticsCollectionEnabled(!kDebugMode)` instead of gating the
handlers on `kDebugMode`.** A3 says wire the handlers only in release so
debug errors keep reaching the console. Same intent, better mechanism:
gating the *assignments* means the error path itself differs between debug
and release, so a bug in a handler would only ever appear in the build you
cannot attach a debugger to. Handlers are always installed and only the
upload is switched off. Console output in debug is unaffected —
`recordFlutterFatalError` calls `FlutterError.presentError` before recording,
and `recordError` defaults `printDetails` to `kDebugMode`.

**2. A5's crash button is gated on `--dart-define=CRASH_TEST=true`, not
`kDebugMode`.** A5 asked for a debug-only button and then said to trigger it
on a release build — which a `kDebugMode` button cannot do, and collection is
off in debug anyway so it would report nothing. The dart-define also means
the button is absent from every ordinary build by construction, so forgetting
to remove it cannot ship it.

## Verified against the installed package, not the spec

`firebase_crashlytics 5.3.0`, read from
`lib/src/firebase_crashlytics.dart`:

- `recordFlutterFatalError(details)` exists and is correct for
  `FlutterError.onError`.
- `recordError(exception, stack, {fatal = false})` — **`fatal` defaults to
  false**, so `PlatformDispatcher` must pass `fatal: true` explicitly.
- `PlatformDispatcher.instance.onError` **must return `true`**. Returning
  false re-raises to the platform, which on Android kills the process —
  reporting a crash would cause one.
- `runZonedGuarded` is no longer part of Firebase's recommended wiring;
  `PlatformDispatcher.instance.onError` supersedes it.

## The Gradle plugin was missing, and a forced dependency bump

A2 says Android needs the Crashlytics Gradle plugin. Neither app had it —
`flutterfire configure` adds it, and Crashlytics was enabled in the console
after the last configure run. Added to both apps:
`com.google.firebase.crashlytics` version `3.0.8`, taken from Google's Maven
metadata for `firebase-crashlytics-gradle`.

**Unplanned but unavoidable:** `firebase_crashlytics 5.3.0` requires
`firebase_core 4.14.0`, and `firebase_auth 6.5.7` fails to compile against
it — `FlutterFirebaseCorePlugin.customAuthDomain` no longer exists, so the
Android build dies in `:firebase_auth:compileDebugJavaWithJavac`. Fixed by
upgrading `firebase_auth` to `6.6.1`, which was already inside the existing
`^6.5.7` constraint; `pub add` had simply done a minimal-change resolution
and left it behind. Worth knowing that adding one Firebase package can
require moving another.

## Where the code lives

Both the wiring and the button are in `volt_core`
(`src/observability/`), not duplicated per app, so the two apps cannot drift
and a third gets it right by default. `volt_core` gains a
`firebase_crashlytics` dependency as a result.

The uid is set in `volt_core`'s `SessionNotifier` — the one place sign-in and
sign-out both happen. It also covers the **restored-session** path in
`build()`, which is the one most launches take; without it every crash from a
returning user would arrive anonymous.

Custom keys: `app`, `api_base_url`, and `booking_status`. The last is written
only on a **status change**, not on every one of the 5s polls — an
unconditional diagnostics write on that path is the amplification the expiry
throttle exists to avoid. No booking codes, per the guardrail: a code
resolves to an address through our own database.

## iOS is unconfigured, deliberately

Dart crashes will report from iOS, but there is no dSYM upload build phase,
so native iOS traces would arrive unsymbolicated. Writing one is unverifiable
from a Windows machine with no iOS build, so it was left undone rather than
guessed at. Android is the only platform being built or shipped today.

## Verification technique worth recording

Whether the Gradle plugin was really applied could not be established from
the APK. `res/raw/firebase_crashlytics_keep.xml` appears in the debug APK but
comes from the SDK AAR, not the plugin; and in release, R8 renames resources
so its absence by filename proves nothing. `assets/crashlytics-build.properties`
was absent from both. The definitive check is asking Gradle:

    cd <app>/android && ./gradlew :app:tasks --all -q | grep -i crashlytics

which lists a "Firebase Crashlytics tasks" group including
`injectCrashlyticsMappingFileIdRelease` and
`uploadCrashlyticsMappingFileRelease`. Confirmed for both apps.
