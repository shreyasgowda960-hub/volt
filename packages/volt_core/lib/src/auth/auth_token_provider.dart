import 'package:firebase_auth/firebase_auth.dart';

/// Supplies a fresh Firebase ID token for API calls.
///
/// The token is NOT stored on VoltSession on purpose: ID tokens expire after
/// one hour. Fetching per-request lets the SDK refresh transparently. A cached
/// token would start returning 401s an hour after sign-in.
abstract interface class AuthTokenProvider {
  Future<String?> currentToken();
}

class FirebaseAuthTokenProvider implements AuthTokenProvider {
  FirebaseAuthTokenProvider({FirebaseAuth? auth})
      : _auth = auth ?? FirebaseAuth.instance;

  final FirebaseAuth _auth;

  @override
  Future<String?> currentToken() async {
    final user = _auth.currentUser;
    if (user == null) return null;
    return user.getIdToken();
  }
}
