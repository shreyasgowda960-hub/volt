import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
    return VoltSession(userId: user.uid, phone: user.phoneNumber ?? '');
  }

  void signIn(VoltSession session) => state = session;

  Future<void> signOut() async {
    // Sign out of Firebase first, or the user stays signed in there and gets
    // silently restored on next launch.
    await FirebaseAuth.instance.signOut();
    state = null;
  }
}

final sessionProvider =
    NotifierProvider<SessionNotifier, VoltSession?>(SessionNotifier.new);
