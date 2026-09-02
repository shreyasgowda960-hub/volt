import 'package:volt_core/volt_core.dart';

import '../domain/booking.dart';
import '../domain/location.dart';
import '../domain/vehicle_type.dart';

abstract interface class BookingRepository {
  Future<Booking> create({
    required Location pickup,
    required Location drop,
    required VehicleType vehicleType,
    required String goodsDescription,
    required double approxWeightKg,
  });

  Future<Booking> byPublicCode(String publicCode);

  /// Free before pickup — a phase 1 decision, so there is no fee messaging.
  /// The server rejects it with 409 once the booking is picked_up or later,
  /// which is why the UI hides the button rather than relying on this call
  /// to fail politely.
  Future<Booking> cancel(String publicCode, {String? reason});
}

class RemoteBookingRepository implements BookingRepository {
  RemoteBookingRepository(this._api);

  final ApiClient _api;

  @override
  Future<Booking> create({
    required Location pickup,
    required Location drop,
    required VehicleType vehicleType,
    required String goodsDescription,
    required double approxWeightKg,
  }) async {
    final json = await _api.post('/api/v1/bookings', {
      'pickup': {'address': pickup.name, 'lat': pickup.lat, 'lng': pickup.lng},
      'drop': {'address': drop.name, 'lat': drop.lat, 'lng': drop.lng},
      'vehicle_type_code': _codeFor(vehicleType),
      'goods_description': goodsDescription,
      'approx_weight_kg': approxWeightKg,
      'payment_method': 'cash',
    });
    return Booking.fromJson(json);
  }

  @override
  Future<Booking> byPublicCode(String publicCode) async {
    final json = await _api.get('/api/v1/bookings/$publicCode');
    return Booking.fromJson(json);
  }

  @override
  Future<Booking> cancel(String publicCode, {String? reason}) async {
    final json = await _api.post(
      '/api/v1/bookings/$publicCode/cancel',
      {'cancellation_reason': ?reason},
    );
    return Booking.fromJson(json);
  }

  String _codeFor(VehicleType v) => switch (v) {
        VehicleType.bike => 'bike',
        VehicleType.threeWheeler => 'three_wheeler',
        VehicleType.miniTruck => 'mini_truck',
      };
}
