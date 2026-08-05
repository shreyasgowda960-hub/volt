import '../domain/volt_session.dart';
import 'auth_repository.dart';

/// Development stand-in. Accepts one hardcoded code and fakes network delay
/// so the loading states are actually exercised.
class FakeAuthRepository implements AuthRepository {
  static const devCode = '123456';

  @override
  Future<String> requestOtp(String phone) async {
    await Future<void>.delayed(const Duration(milliseconds: 1200));
    return 'fake-verification-id';
  }

  @override
  Future<VoltSession> verifyOtp({
    required String verificationId,
    required String phone,
    required String code,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 900));
    if (code != devCode) throw const InvalidOtpException();
    return VoltSession(userId: 'dev-user', phone: phone);
  }
}
