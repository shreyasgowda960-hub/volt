import 'volt_session.dart';

/// The contract every auth implementation honours. Firebase phone auth
/// slots in behind this later without a single screen changing.
abstract interface class AuthRepository {
  /// Sends an OTP to [phone] (E.164). Returns an opaque verification id.
  Future<String> requestOtp(String phone);

  /// Throws [InvalidOtpException] if the code is wrong.
  Future<VoltSession> verifyOtp({
    required String verificationId,
    required String phone,
    required String code,
  });
}
