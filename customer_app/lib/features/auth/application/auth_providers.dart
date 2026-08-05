import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/auth_repository.dart';
import '../data/fake_auth_repository.dart';
import '../domain/volt_session.dart';

/// Swap this one line for FirebaseAuthRepository() when phase 1 auth lands.
final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return FakeAuthRepository();
});

class SessionNotifier extends Notifier<VoltSession?> {
  @override
  VoltSession? build() => null;

  void signIn(VoltSession session) => state = session;
  void signOut() => state = null;
}

final sessionProvider =
    NotifierProvider<SessionNotifier, VoltSession?>(SessionNotifier.new);
