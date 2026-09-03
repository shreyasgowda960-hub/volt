import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../observability/crash_reporting.dart';
import 'auth_repository.dart';
import 'auth_token_provider.dart';
import 'firebase_auth_repository.dart';
import 'volt_session.dart';

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return FirebaseAuthRepository();
});

final authTokenProvider = Provider<AuthTokenProvider>((ref) {
  return FirebaseAuthTokenProvider();
});

class SessionNotifier extends Notifier<VoltSession?> {
  @override
  VoltSession? build() {
    // Firebase persists sign-in across restarts; currentUser is available
    // synchronously right after Firebase.initializeApp in main().
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return null;

    // Restored session, not a fresh sign-in — but it still needs the uid on
    // crash reports, and this is the path most launches take. Missing it here
    // would mean every crash from a returning user came back anonymous.
    setCrashReportingUser(user.uid);

    return VoltSession(userId: user.uid, phone: user.phoneNumber ?? '');
  }

  void signIn(VoltSession session) {
    // Crash reports carry the Firebase uid and nothing else identifying —
    // never session.phone. See setCrashReportingUser.
    setCrashReportingUser(session.userId);
    state = session;
  }

  Future<void> signOut() async {
    // Sign out of Firebase first, or the user stays signed in there and gets
    // silently restored on next launch.
    await FirebaseAuth.instance.signOut();
    // Cleared so a crash after sign-out is not attributed to whoever was
    // last signed in on this device.
    await setCrashReportingUser(null);
    state = null;
  }
}

final sessionProvider =
    NotifierProvider<SessionNotifier, VoltSession?>(SessionNotifier.new);
