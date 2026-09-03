import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import 'features/auth/presentation/phone_entry_screen.dart';
import 'features/booking/presentation/booking_home_screen.dart';
import 'firebase_options.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  // After Firebase, before runApp: the handlers need Firebase up, and an
  // error thrown during the first frame should already be reportable.
  await initCrashReporting(appName: 'customer');
  runApp(const ProviderScope(child: VoltApp()));
}

class VoltApp extends ConsumerWidget {
  const VoltApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);

    return MaterialApp(
      title: 'VOLT',
      debugShowCheckedModeBanner: false,
      theme: buildVoltTheme(),
      home: session == null
          ? const PhoneEntryScreen()
          : const BookingHomeScreen(),
    );
  }
}
