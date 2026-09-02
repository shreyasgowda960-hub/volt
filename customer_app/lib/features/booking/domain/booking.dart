import 'assigned_driver.dart';
import 'booking_status.dart';

/// Mirrors the API's booking payload.
///
/// Two server schemas land in this one class: `BookingResponse` (from
/// POST /bookings and POST /bookings/{code}/cancel) and the richer
/// `BookingDetailResponse` (from the customer GETs, which add the driver and
/// the lifecycle timestamps). Every field unique to the detail shape is
/// therefore read as optional — parsing the narrow shape must not throw, or
/// creating a booking would fail on the response to its own POST.
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
    this.driver,
    this.driverAssignedAt,
    this.pickedUpAt,
    this.deliveredAt,
    this.cancelledAt,
    this.expiredAt,
    this.cancelledBy,
    this.cancellationReason,
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
      driver: json['driver'] == null
          ? null
          : AssignedDriver.fromJson(json['driver'] as Map<String, dynamic>),
      driverAssignedAt: _parseTime(json['driver_assigned_at']),
      pickedUpAt: _parseTime(json['picked_up_at']),
      deliveredAt: _parseTime(json['delivered_at']),
      cancelledAt: _parseTime(json['cancelled_at']),
      expiredAt: _parseTime(json['expired_at']),
      cancelledBy: json['cancelled_by'] as String?,
      cancellationReason: json['cancellation_reason'] as String?,
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

  final AssignedDriver? driver;

  final DateTime? driverAssignedAt;
  final DateTime? pickedUpAt;
  final DateTime? deliveredAt;
  final DateTime? cancelledAt;
  final DateTime? expiredAt;

  final String? cancelledBy;
  final String? cancellationReason;

  double get quotedFareInr => quotedFarePaise / 100;

  /// What the customer actually owes: the settled amount if the trip is done,
  /// otherwise the quote they agreed to.
  double get payableFareInr => (finalFarePaise ?? quotedFarePaise) / 100;

  static DateTime? _parseTime(Object? raw) =>
      raw == null ? null : DateTime.parse(raw as String).toLocal();

  static BookingStatus _statusFromCode(String code) => switch (code) {
        'pending' => BookingStatus.pending,
        'driver_assigned' => BookingStatus.driverAssigned,
        'picked_up' => BookingStatus.pickedUp,
        'delivered' => BookingStatus.delivered,
        'cancelled' => BookingStatus.cancelled,
        'expired' => BookingStatus.expired,
        _ => throw ArgumentError('Unhandled booking status: $code'),
      };
}
