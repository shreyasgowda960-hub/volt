import 'booking_status.dart';

/// Mirrors `BookingResponse` from the API.
class Booking {
  const Booking({
    required this.publicCode,
    required this.status,
    required this.vehicleTypeCode,
    required this.pickupAddress,
    required this.dropAddress,
    required this.goodsDescription,
    required this.approxWeightKg,
    required this.quotedFarePaise,
    required this.quotedDistanceM,
    required this.quotedEtaMinutes,
    required this.finalFarePaise,
    required this.paymentMethod,
    required this.createdAt,
  });

  factory Booking.fromJson(Map<String, dynamic> json) {
    return Booking(
      publicCode: json['public_code'] as String,
      status: _statusFromCode(json['status'] as String),
      vehicleTypeCode: json['vehicle_type_code'] as String,
      pickupAddress: json['pickup_address'] as String,
      dropAddress: json['drop_address'] as String,
      goodsDescription: json['goods_description'] as String,
      approxWeightKg: (json['approx_weight_kg'] as num).toDouble(),
      quotedFarePaise: json['quoted_fare_paise'] as int,
      quotedDistanceM: json['quoted_distance_m'] as int,
      quotedEtaMinutes: json['quoted_eta_minutes'] as int,
      finalFarePaise: json['final_fare_paise'] as int?,
      paymentMethod: json['payment_method'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }

  final String publicCode;
  final BookingStatus status;
  final String vehicleTypeCode;
  final String pickupAddress;
  final String dropAddress;
  final String goodsDescription;
  final double approxWeightKg;
  final int quotedFarePaise;
  final int quotedDistanceM;
  final int quotedEtaMinutes;
  final int? finalFarePaise;
  final String paymentMethod;
  final DateTime createdAt;

  double get quotedFareInr => quotedFarePaise / 100;

  static BookingStatus _statusFromCode(String code) => switch (code) {
        'pending' => BookingStatus.searching,
        'driver_assigned' => BookingStatus.driverAssigned,
        'picked_up' => BookingStatus.pickedUp,
        'delivered' => BookingStatus.delivered,
        _ => throw ArgumentError('Unhandled booking status: $code'),
      };
}
