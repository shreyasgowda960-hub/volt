import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/theme/app_theme.dart';
import 'features/auth/application/auth_providers.dart';
import 'features/auth/presentation/phone_entry_screen.dart';
import 'features/booking/presentation/booking_home_screen.dart';
import 'firebase_options.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
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
