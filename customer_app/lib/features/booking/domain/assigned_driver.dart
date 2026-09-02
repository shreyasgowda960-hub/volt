/// The driver on a booking, as the customer is allowed to see them.
///
/// Mirrors `AssignedDriverResponse`. [phone] is nullable and the server nulls
/// it once the booking is terminal — the number is operational data for a live
/// trip, not something a customer should still hold months later. Nothing here
/// needs to enforce that; the UI simply hides the Call button when it is null.
class AssignedDriver {
  const AssignedDriver({
    required this.name,
    required this.phone,
    required this.vehicleNumber,
    required this.vehicleTypeCode,
    required this.rating,
  });

  factory AssignedDriver.fromJson(Map<String, dynamic> json) {
    return AssignedDriver(
      name: json['name'] as String,
      phone: json['phone'] as String?,
      vehicleNumber: json['vehicle_number'] as String,
      vehicleTypeCode: json['vehicle_type_code'] as String,
      rating: (json['rating'] as num?)?.toDouble(),
    );
  }

  final String name;
  final String? phone;
  final String vehicleNumber;
  final String vehicleTypeCode;
  final double? rating;

  bool get isCallable => phone != null && phone!.isNotEmpty;
}
