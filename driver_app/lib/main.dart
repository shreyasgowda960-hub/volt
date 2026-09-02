import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import 'features/auth/presentation/phone_entry_screen.dart';
import 'features/driver/application/driver_providers.dart';
import 'features/driver/presentation/driver_home_screen.dart';
import 'features/driver/presentation/driver_registration_screen.dart';
import 'firebase_options.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
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

/// Three-state routing lives here rather than in VoltDriverApp so the
/// signed-out branch above never touches driverProfileProvider — there's no
/// token yet for it to call the API with.
class _ProfileGate extends ConsumerWidget {
  const _ProfileGate();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profileAsync = ref.watch(driverProfileProvider);

    return profileAsync.when(
      // Async by nature — show a spinner, not a flash of the wrong screen.
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  error is ApiException ? error.message : 'Something went wrong.',
                  style: const TextStyle(color: AppColors.textSecondary),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: () => ref.invalidate(driverProfileProvider),
                  child: const Text('Retry'),
                ),
              ],
            ),
          ),
        ),
      ),
      data: (profile) => profile == null
          ? const DriverRegistrationScreen()
          : const DriverHomeScreen(),
    );
  }
}
