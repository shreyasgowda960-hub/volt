import 'dart:math';

import '../domain/fare_estimate.dart';
import '../domain/location.dart';
import '../domain/vehicle_type.dart';

abstract interface class FareEstimator {
  Future<List<FareEstimate>> estimateAll(Location pickup, Location drop);
}

/// DISPLAY ONLY. The server is the authority on price — see
/// RemoteFareEstimator. This exists as an offline fallback and for tests, and
/// its output must never be sent to the server or treated as a real quote.
class LocalFareEstimator implements FareEstimator {
  static const _earthRadiusKm = 6371.0;
  static const _roadFactor = 1.4;
  static const _avgSpeedKmh = 20.0;

  double _haversineKm(Location a, Location b) {
    final dLat = _deg2rad(b.lat - a.lat);
    final dLng = _deg2rad(b.lng - a.lng);
    final h = sin(dLat / 2) * sin(dLat / 2) +
        cos(_deg2rad(a.lat)) *
            cos(_deg2rad(b.lat)) *
            sin(dLng / 2) *
            sin(dLng / 2);
    return _earthRadiusKm * 2 * atan2(sqrt(h), sqrt(1 - h));
  }

  double _deg2rad(double deg) => deg * (pi / 180);

  @override
  Future<List<FareEstimate>> estimateAll(Location pickup, Location drop) async {
    final distanceKm = _haversineKm(pickup, drop) * _roadFactor;
    final etaMinutes = ((distanceKm / _avgSpeedKmh) * 60).round();

    return VehicleType.values.map((vehicle) {
      final billableKm = max(0.0, distanceKm - vehicle.includedKm);
      final rawFare = vehicle.baseFare + billableKm * vehicle.perKmRate;
      return FareEstimate(
        vehicleType: vehicle,
        distanceKm: distanceKm,
        fareInr: max(rawFare, vehicle.minFare),
        etaMinutes: etaMinutes,
      );
    }).toList();
  }
}
