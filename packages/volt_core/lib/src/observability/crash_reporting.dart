import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/foundation.dart';

import '../config/app_config.dart';

/// Wires Crashlytics to every error path Flutter has.
///
/// Call once from main(), after Firebase.initializeApp and before runApp.
/// Both apps call the same function so neither can drift from the other, and
/// so a third app gets it right by construction.
///
/// [appName] is a short label — "customer" or "driver" — attached as a custom
/// key so reports from the two apps are separable in the console. It is not a
/// flavour in the Gradle sense; there is only one build type per app today.
Future<void> initCrashReporting({required String appName}) async {
  // Framework errors: anything thrown inside the widget/render pipeline.
  //
  // recordFlutterFatalError calls FlutterError.presentError itself before
  // recording, so assigning this does NOT swallow console output in debug —
  // the red screen and the stack trace still appear as they always did.
  FlutterError.onError = FirebaseCrashlytics.instance.recordFlutterFatalError;

  // Async errors that never reach the framework at all: a Future that throws
  // with nobody awaiting it, a timer callback, an isolate error. This is
  // where most real crashes live, and it is the handler most often left out —
  // an app can look fully instrumented and report none of them.
  PlatformDispatcher.instance.onError = (error, stack) {
    FirebaseCrashlytics.instance.recordError(error, stack, fatal: true);
    // MUST be true: returning false tells the engine the error is unhandled
    // and re-raises it to the platform, which on Android terminates the
    // process. Reporting a crash is not a reason to cause one.
    return true;
  };

  // Native crashes need no wiring — the plugin installs its own signal
  // handlers once the Gradle plugin is applied.

  // Collection is disabled in debug rather than skipping the handlers above.
  //
  // Gating the assignments on kDebugMode would mean the error path itself
  // differs between debug and release, so a mistake in a handler would only
  // ever surface in the build you cannot attach a debugger to. This way both
  // builds run identical code and only the upload differs. Console output in
  // debug is unaffected: presentError still runs, and recordError defaults
  // printDetails to kDebugMode.
  await FirebaseCrashlytics.instance
      .setCrashlyticsCollectionEnabled(!kDebugMode);

  // Triage context. Deliberately nothing that identifies a person: no phone
  // number, no name, no address, and no booking code — a booking code
  // resolves to an address through our own database, which makes it PII with
  // one extra step.
  await FirebaseCrashlytics.instance.setCustomKey('app', appName);
  // Which backend the build points at. The single most useful key here: a
  // crash from a LAN-IP build is somebody's dev machine, not production.
  await FirebaseCrashlytics.instance
      .setCustomKey('api_base_url', AppConfig.apiBaseUrl);
}

/// Attaches the signed-in Firebase uid to subsequent reports, or clears it.
///
/// The uid alone answers the question triage actually needs — "is this one
/// user hitting this five times, or five users once each" — without putting a
/// phone number in a crash report. Going from a uid to a person requires our
/// own database, which is the right amount of friction.
///
/// Wrapped because it must never be the reason sign-in fails. Crashlytics
/// throws if Firebase was not initialised, which is the normal state in a
/// unit test that touches the session but never boots Firebase.
Future<void> setCrashReportingUser(String? uid) async {
  try {
    await FirebaseCrashlytics.instance.setUserIdentifier(uid ?? '');
  } catch (error, stack) {
    // Not reported to Crashlytics — if Crashlytics is what failed, calling it
    // again is not going to help.
    debugPrint('Could not set Crashlytics user identifier: $error\n$stack');
  }
}

/// Records a non-fatal error with context, for paths that already handle
/// their own failures but are worth knowing about.
///
/// [reason] is a short description, not user data.
Future<void> recordHandledError(
  Object error,
  StackTrace? stack, {
  required String reason,
}) async {
  try {
    await FirebaseCrashlytics.instance
        .recordError(error, stack, reason: reason, fatal: false);
  } catch (_) {
    // Same reasoning as above.
  }
}

/// Sets a custom key, ignoring failures.
///
/// Callers are usually on a hot path (the 5s pollers) and must not gain a
/// failure mode from a diagnostics write.
Future<void> setCrashReportingKey(String key, Object value) async {
  try {
    await FirebaseCrashlytics.instance.setCustomKey(key, value);
  } catch (_) {}
}
