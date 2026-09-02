class DriverProfile {
  const DriverProfile({
    required this.id,
    required this.phone,
    required this.name,
    required this.vehicleNumber,
    required this.vehicleTypeCode,
    required this.isOnline,
    required this.isVerified,
    this.rating,
  });

  final int id;
  final String phone;
  final String name;
  final String vehicleNumber;
  final String vehicleTypeCode;
  final bool isOnline;
  final bool isVerified;
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
      rating: (json['rating'] as num?)?.toDouble(),
    );
  }
}
