import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';

import '../domain/volt_session.dart';
import 'auth_repository.dart';

/// Real phone auth. Slots in behind AuthRepository with no screen changes —
/// this is the payoff for the interface pattern.
class FirebaseAuthRepository implements AuthRepository {
  FirebaseAuthRepository({FirebaseAuth? auth})
      : _auth = auth ?? FirebaseAuth.instance;

  final FirebaseAuth _auth;

  @override
  Future<String> requestOtp(String phone) async {
    // verifyPhoneNumber is callback-based; the interface is Future-based.
    // A Completer bridges the two.
    final completer = Completer<String>();

    await _auth.verifyPhoneNumber(
      phoneNumber: phone,
      timeout: const Duration(seconds: 60),
      verificationCompleted: (PhoneAuthCredential credential) {
        // Android can auto-read the SMS and verify without user input.
        // Deliberately ignored: the OTP screen expects a verificationId and
        // handles the code itself. Revisit if auto-retrieval is wanted later.
      },
      verificationFailed: (FirebaseAuthException e) {
        if (!completer.isCompleted) completer.completeError(e);
      },
      codeSent: (String verificationId, int? resendToken) {
        if (!completer.isCompleted) completer.complete(verificationId);
      },
      codeAutoRetrievalTimeout: (String verificationId) {
        // Auto-retrieval window closed. Manual entry still works.
      },
    );

    return completer.future;
  }

  @override
  Future<VoltSession> verifyOtp({
    required String verificationId,
    required String phone,
    required String code,
  }) async {
    final credential = PhoneAuthProvider.credential(
      verificationId: verificationId,
      smsCode: code,
    );

    try {
      final result = await _auth.signInWithCredential(credential);
      final user = result.user;
      if (user == null) {
        throw StateError('Firebase returned no user after sign-in');
      }
      return VoltSession(
        userId: user.uid,
        phone: user.phoneNumber ?? phone,
      );
    } on FirebaseAuthException catch (e) {
      // Verified against firebase_auth 6.5.7's signInWithCredential docs:
      // 'session-expired' is not a real code for this call (it only exists
      // in the Windows-native plugin). An expired/garbage verification
      // session surfaces as 'invalid-verification-id' on Android.
      if (e.code == 'invalid-verification-code' ||
          e.code == 'invalid-verification-id') {
        throw const InvalidOtpException();
      }
      rethrow;
    }
  }
}
