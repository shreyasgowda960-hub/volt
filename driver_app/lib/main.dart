import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import 'features/auth/presentation/phone_entry_screen.dart';
import 'features/driver/application/driver_providers.dart';
import 'features/driver/presentation/driver_home_screen.dart';
import 'features/driver/domain/driver_profile.dart';
import 'features/driver/presentation/driver_registration_screen.dart';
import 'features/verification/domain/driver_document.dart';
import 'features/verification/presentation/document_upload_screen.dart';
import 'features/verification/presentation/pending_review_screen.dart';
import 'firebase_options.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  // After Firebase, before runApp: the handlers need Firebase up, and an
  // error thrown during the first frame should already be reportable.
  await initCrashReporting(appName: 'driver');
  runApp(const ProviderScope(child: VoltDriverApp()));
}

class VoltDriverApp extends ConsumerWidget {
  const VoltDriverApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);

    return MaterialApp(
      title: 'VOLT Driver',
      debugShowCheckedModeBanner: false,
      theme: buildVoltTheme(),
      home: session == null ? const PhoneEntryScreen() : const _ProfileGate(),
    );
  }
}

/// Four-state routing lives here rather than in VoltDriverApp so the
/// signed-out branch above never touches driverProfileProvider — there's no
/// token yet for it to call the API with.
///
/// The states, in order (spec 017):
///   session == null                            -> PhoneEntryScreen (above)
///   profile == null                            -> DriverRegistrationScreen
///   pending | rejected                         -> DocumentUploadScreen
///   submitted                                  -> PendingReviewScreen
///   approved                                   -> DriverHomeScreen
///
/// Routing is on verification_status, NOT is_verified: the bool cannot tell
/// "upload something" from "wait for us", and those are different screens.
class _ProfileGate extends ConsumerWidget {
  const _ProfileGate();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profileAsync = ref.watch(driverProfileProvider);

    // A FAILED REFRESH MUST NEVER CLEAR THE LAST KNOWN GOOD STATE — the same
    // rule polling follows (spec 011), and routing is the worst place to break
    // it. PendingReviewScreen's pull-to-refresh runs through this provider, so
    // without this a failed pull on a weak connection would swap the driver's
    // screen for a generic error page. Only a FIRST load with nothing to fall
    // back on reaches the error branch below.
    if (profileAsync.hasValue) {
      return _screenFor(profileAsync.requireValue);
    }

    return profileAsync.when(
      // Async by nature — show a spinner, not a flash of the wrong screen.
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      ),
      // RETRY IS NOT ENOUGH ON ITS OWN, and that is not hypothetical: a
      // routing bug once parked drivers here with a message that would never
      // change no matter how many times they tapped it. Retry only helps a
      // TRANSIENT failure; anything structural — a server older than the app,
      // a token for an account in a state this build cannot read — is a
      // permanent dead end with no way back to the phone entry screen.
      //
      // Sign out is the honest second action. It is the one escape that works
      // without knowing what went wrong, because it returns to session == null
      // and lets the driver start over.
      //
      // Deliberately NOT routing to registration on an unknown error. Guessing
      // "you must not be registered" from a failure we could not classify
      // would show the registration form to drivers who already have an
      // account, and their attempt to register would 409.
      error: (error, _) => Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.xl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  error is ApiException ? error.message : 'Something went wrong.',
                  style: const TextStyle(color: AppColors.textSecondary),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: AppSpacing.lg),
                FilledButton(
                  onPressed: () => ref.invalidate(driverProfileProvider),
                  child: const Text('Retry'),
                ),
                const SizedBox(height: AppSpacing.sm),
                TextButton(
                  onPressed: () => ref.read(sessionProvider.notifier).signOut(),
                  child: const Text('Sign out'),
                ),
              ],
            ),
          ),
        ),
      ),
      data: _screenFor,
    );
  }

  Widget _screenFor(DriverProfile? profile) {
    if (profile == null) return const DriverRegistrationScreen();

    return switch (profile.verificationStatus) {
      // Rejected joins pending rather than getting a screen of its own — the
      // remedy for both is the same, and the upload screen already shows the
      // reason against the document that failed.
      VerificationStatus.pending ||
      VerificationStatus.rejected =>
        const DocumentUploadScreen(),
      VerificationStatus.submitted => const PendingReviewScreen(),
      VerificationStatus.approved => const DriverHomeScreen(),
    };
  }
}
