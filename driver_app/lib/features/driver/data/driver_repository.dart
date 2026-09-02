import 'package:volt_core/volt_core.dart';

import '../../jobs/domain/job.dart';
import '../domain/driver_profile.dart';
import '../domain/vehicle_type_option.dart';

/// Thrown by [DriverRepository.me] when the token is valid but there is no
/// drivers row for this uid yet — a routing signal (show registration), not
/// an error state.
class DriverNotRegistered implements Exception {
  const DriverNotRegistered();
}

/// Thrown by [DriverRepository.accept] when another driver's accept won the
/// race. A normal outcome of a shared job board, not a failure.
class JobAlreadyClaimed implements Exception {
  const JobAlreadyClaimed();
}

/// Thrown by [DriverRepository.accept] when the booking expired (lazy
/// expiry swept it) before this accept landed. Deliberately distinct from
/// [JobAlreadyClaimed] — the server tells these apart precisely so the
/// driver isn't told "someone else took it" when nobody did.
class JobExpired implements Exception {
  const JobExpired();
}

abstract interface class DriverRepository {
  Future<List<VehicleTypeOption>> vehicleTypes();

  /// Throws [DriverNotRegistered] on 403 "Not registered as a driver".
  Future<DriverProfile> me();

  Future<DriverProfile> register({
    required String name,
    required String vehicleNumber,
    required String vehicleTypeCode,
  });

  Future<DriverProfile> setOnline(bool online);

  Future<List<Job>> availableJobs();
  Future<List<Job>> myJobs();

  /// Throws [JobAlreadyClaimed] or [JobExpired] on 409.
  Future<Job> accept(String publicCode);

  Future<Job> markPickedUp(String publicCode);
  Future<Job> markDelivered(String publicCode);
}

class RemoteDriverRepository implements DriverRepository {
  RemoteDriverRepository(this._api);

  final ApiClient _api;

  @override
  Future<List<VehicleTypeOption>> vehicleTypes() async {
    final json = await _api.getList('/api/v1/vehicle-types');
    return json
        .map((v) => VehicleTypeOption.fromJson(v as Map<String, dynamic>))
        .toList();
  }

  @override
  Future<DriverProfile> me() async {
    try {
      final json = await _api.get('/api/v1/drivers/me');
      return DriverProfile.fromJson(json);
    } on ApiException catch (e) {
      if (e.statusCode == 403 && e.message.contains('Not registered')) {
        throw const DriverNotRegistered();
      }
      rethrow;
    }
  }

  @override
  Future<DriverProfile> register({
    required String name,
    required String vehicleNumber,
    required String vehicleTypeCode,
  }) async {
    final json = await _api.post('/api/v1/drivers/register', {
      'name': name,
      'vehicle_number': vehicleNumber,
      'vehicle_type_code': vehicleTypeCode,
    });
    return DriverProfile.fromJson(json);
  }

  @override
  Future<DriverProfile> setOnline(bool online) async {
    final json = await _api.patch('/api/v1/drivers/me/availability', {
      'is_online': online,
    });
    return DriverProfile.fromJson(json);
  }

  @override
  Future<List<Job>> availableJobs() async {
    final json = await _api.getList('/api/v1/drivers/jobs');
    return json.map((j) => Job.fromJson(j as Map<String, dynamic>)).toList();
  }

  @override
  Future<List<Job>> myJobs() async {
    final json = await _api.getList('/api/v1/drivers/bookings');
    return json.map((j) => Job.fromJson(j as Map<String, dynamic>)).toList();
  }

  @override
  Future<Job> accept(String publicCode) async {
    try {
      final json = await _api.post('/api/v1/bookings/$publicCode/accept', {});
      return Job.fromJson(json);
    } on ApiException catch (e) {
      if (e.statusCode == 409) {
        final msg = e.message.toLowerCase();
        if (msg.contains('expired')) throw const JobExpired();
        if (msg.contains('no longer available')) {
          throw const JobAlreadyClaimed();
        }
      }
      rethrow;
    }
  }

  @override
  Future<Job> markPickedUp(String publicCode) async {
    final json = await _api.post('/api/v1/bookings/$publicCode/pickup', {});
    return Job.fromJson(json);
  }

  @override
  Future<Job> markDelivered(String publicCode) async {
    final json = await _api.post('/api/v1/bookings/$publicCode/deliver', {});
    return Job.fromJson(json);
  }
}
