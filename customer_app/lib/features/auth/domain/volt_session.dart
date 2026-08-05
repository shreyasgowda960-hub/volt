class VoltSession {
  const VoltSession({required this.userId, required this.phone});

  /// E.164 format, e.g. +919876543210.
  final String phone;
  final String userId;
}

class InvalidOtpException implements Exception {
  const InvalidOtpException();
}
