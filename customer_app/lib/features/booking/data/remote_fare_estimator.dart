import '../../../core/network/api_client.dart';
import '../domain/fare_estimate.dart';
import '../domain/location.dart';
import '../domain/vehicle_type.dart';
import 'fare_estimator.dart';

class RemoteFareEstimator implements FareEstimator {
  RemoteFareEstimator(this._api);

  final ApiClient _api;

  @override
  Future<List<FareEstimate>> estimateAll(Location pickup, Location drop) async {
    final json = await _api.post('/api/v1/bookings/estimate', {
      'pickup': {
        'address': pickup.name,
        'lat': pickup.lat,
        'lng': pickup.lng,
      },
      'drop': {
        'address': drop.name,
        'lat': drop.lat,
        'lng': drop.lng,
      },
    });

    final options = (json['options'] as List<dynamic>? ?? <dynamic>[]);
    return options.map((raw) {
      final o = raw as Map<String, dynamic>;
      return FareEstimate(
        vehicleType: _vehicleFromCode(o['vehicle_type_code'] as String),
        distanceKm: (o['distance_m'] as num) / 1000,
        fareInr: (o['fare_paise'] as num) / 100,
        etaMinutes: o['eta_minutes'] as int,
      );
    }).toList();
  }

  VehicleType _vehicleFromCode(String code) => switch (code) {
        'bike' => VehicleType.bike,
        'three_wheeler' => VehicleType.threeWheeler,
        'mini_truck' => VehicleType.miniTruck,
        _ => throw ArgumentError('Unknown vehicle type code: $code'),
      };
}
