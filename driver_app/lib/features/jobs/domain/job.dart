enum JobStatus {
  pending,
  driverAssigned,
  pickedUp,
  delivered,
  cancelled,
  expired;

  /// This driver is on the hook for it: mirrors the server's
  /// one_active_booking_per_driver index, which counts exactly these two.
  bool get isActive =>
      this == JobStatus.driverAssigned || this == JobStatus.pickedUp;
}

JobStatus _statusFromJson(String raw) {
  switch (raw) {
    case 'pending':
      return JobStatus.pending;
    case 'driver_assigned':
      return JobStatus.driverAssigned;
    case 'picked_up':
      return JobStatus.pickedUp;
    case 'delivered':
      return JobStatus.delivered;
    case 'cancelled':
      return JobStatus.cancelled;
    case 'expired':
      return JobStatus.expired;
    default:
      throw ArgumentError('Unknown booking status: $raw');
  }
}

/// A booking as the driver sees it. Same underlying resource as customer_app's
/// Booking, but that type stays in customer_app (feature-specific per spec
/// 009) — this is its driver-facing counterpart, not a duplicate of shared code.
class Job {
  const Job({
    required this.publicCode,
    required this.status,
    required this.pickupAddress,
    required this.dropAddress,
    required this.goodsDescription,
    required this.approxWeightKg,
    required this.quotedFarePaise,
    required this.quotedDistanceM,
    required this.quotedEtaMinutes,
    required this.createdAt,
  });

  final String publicCode;
  final JobStatus status;
  final String pickupAddress;
  final String dropAddress;
  final String goodsDescription;
  final double approxWeightKg;
  final int quotedFarePaise;
  final int quotedDistanceM;
  final int quotedEtaMinutes;
  final DateTime createdAt;

  double get quotedFareInr => quotedFarePaise / 100;

  factory Job.fromJson(Map<String, dynamic> json) {
    return Job(
      publicCode: json['public_code'] as String,
      status: _statusFromJson(json['status'] as String),
      pickupAddress: json['pickup_address'] as String,
      dropAddress: json['drop_address'] as String,
      goodsDescription: json['goods_description'] as String,
      approxWeightKg: (json['approx_weight_kg'] as num).toDouble(),
      quotedFarePaise: json['quoted_fare_paise'] as int,
      quotedDistanceM: json['quoted_distance_m'] as int,
      quotedEtaMinutes: json['quoted_eta_minutes'] as int,
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}
