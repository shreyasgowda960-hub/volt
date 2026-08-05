import 'vehicle_type.dart';

/// Shaped to match the future POST /api/v1/bookings/estimate response so the
/// client-side estimator can be deleted without touching call sites.
class FareEstimate {
  const FareEstimate({
    required this.vehicleType,
    required this.distanceKm,
    required this.fareInr,
    required this.etaMinutes,
  });

  final VehicleType vehicleType;
  final double distanceKm;
  final double fareInr;
  final int etaMinutes;
}
