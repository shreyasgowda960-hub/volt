import '../../verification/domain/driver_document.dart';

class DriverProfile {
  const DriverProfile({
    required this.id,
    required this.phone,
    required this.name,
    required this.vehicleNumber,
    required this.vehicleTypeCode,
    required this.isOnline,
    required this.isVerified,
    required this.verificationStatus,
    this.rating,
  });

  final int id;
  final String phone;
  final String name;
  final String vehicleNumber;
  final String vehicleTypeCode;
  final bool isOnline;

  /// Derived server-side from [verificationStatus] == approved, and the thing
  /// every operational endpoint gates on. The app routes on the status rather
  /// than this bool, because four screens cannot be chosen from two values.
  final bool isVerified;
  final VerificationStatus verificationStatus;
  final double? rating;

  factory DriverProfile.fromJson(Map<String, dynamic> json) {
    return DriverProfile(
      id: json['id'] as int,
      phone: json['phone'] as String,
      name: json['name'] as String,
      vehicleNumber: json['vehicle_number'] as String,
      vehicleTypeCode: json['vehicle_type_code'] as String,
      isOnline: json['is_online'] as bool,
      isVerified: json['is_verified'] as bool,
      verificationStatus: VerificationStatus.fromWire(
        json['verification_status'] as String?,
      ),
      rating: (json['rating'] as num?)?.toDouble(),
    );
  }
}
