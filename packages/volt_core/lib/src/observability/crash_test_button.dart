import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/material.dart';

/// Whether this build carries the crash-test affordance.
///
/// Gated on a --dart-define rather than on kDebugMode, and that is the whole
/// point. Crashlytics collection is off in debug, so a debug-only button
/// cannot actually produce a report — the thing being tested only happens in
/// a release build. A kDebugMode button would be untriggerable exactly where
/// it matters.
///
/// A dart-define also means the button is absent from every normal build by
/// construction, so forgetting to delete it cannot ship it:
///
///   flutter build apk --release --dart-define=CRASH_TEST=true \
///     --dart-define=API_BASE_URL=https://volt-api-951s.onrender.com
const bool kCrashTestEnabled = bool.fromEnvironment('CRASH_TEST');

/// Forces a native crash, to prove the reporting pipeline end to end.
///
/// Renders nothing unless [kCrashTestEnabled]. A crash reporter nobody has
/// watched fire is not a crash reporter: the plugin can be installed, the
/// handlers wired and the Gradle plugin applied, and reports can still fail
/// to arrive because Crashlytics was never enabled in the console for that
/// app. Only a real report proves it.
///
/// Uses FirebaseCrashlytics.instance.crash(), which crashes natively — that
/// exercises the native path rather than the Dart handlers, so a report
/// arriving proves the whole chain including the Gradle plugin.
class CrashTestButton extends StatelessWidget {
  const CrashTestButton({super.key});

  @override
  Widget build(BuildContext context) {
    if (!kCrashTestEnabled) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
      child: OutlinedButton.icon(
        onPressed: () {
          // Deliberately not wrapped: the process is supposed to die here.
          FirebaseCrashlytics.instance.crash();
        },
        icon: const Icon(Icons.bug_report_outlined),
        label: const Text('Force a test crash'),
      ),
    );
  }
}
