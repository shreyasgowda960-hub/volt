import 'package:volt_core/volt_core.dart';

import '../../jobs/domain/job.dart';
import '../../verification/domain/driver_document.dart';
import '../domain/driver_profile.dart';
import '../domain/vehicle_type_option.dart';

/// The server's machine-readable reason on a driver-auth 403. Branch on this,
/// never on the message — the message is prose shown to a person and may be
/// reworded at any time. See app/driver_auth.py.
const _kDriverNotRegistered = 'driver_not_registered';

/// LEGACY FALLBACK, and it is load-bearing right now.
///
/// Servers older than spec 017 send no `code` at all, and the deployed backend
/// is one of them until this branch merges. Without this the app reads a null
/// code, fails the check below, and routes an unregistered driver to the
/// error screen instead of the registration form — which is precisely the bug
/// this constant exists to close, observed on a real device against
/// production.
///
/// Substring-matching prose is as fragile as it looks; it is here because the
/// alternative is worse, and because an app always has to tolerate a server
/// older than itself. REMOVE IT once the coded backend has been deployed long
/// enough that no older server can be reached — the server is one deployment,
/// so the trigger is simply "017 is live in production".
const _kLegacyNotRegisteredFragment = 'Not registered';

/// True when a 403 means "this token has no driver row", by either the coded
/// answer or the legacy one.
///
/// The legacy branch is deliberately gated on `code == null`. A server that
/// DID send a code has already given its answer, and falling back to prose
/// there would let an unrelated 403 whose message happened to contain the
/// fragment be read as "not registered".
bool _isNotRegistered(ApiException e) {
  if (e.statusCode != 403) return false;
  if (e.code != null) return e.code == _kDriverNotRegistered;
  return e.message.contains(_kLegacyNotRegisteredFragment);
}

/// Thrown by [DriverRepository.me] when the token is valid but there is no
/// drivers row for this uid yet — a routing signal (show registration), not
/// an error state.
///
/// Distinguished from "registered but unverified" by the server's error CODE.
/// Both are 403s, and they route to completely different screens.
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

  /// Throws [DriverNotRegistered] on a 403 coded `driver_not_registered`.
  Future<DriverProfile> me();

  /// The driver's own documents and verification status.
  ///
  /// No signed URLs come back — the backend does not issue them on this
  /// endpoint. A driver took the photo; they do not need to re-read it.
  Future<DriverVerification> myDocuments();

  /// Upload one document. A MUTATION: call it from an event handler via
  /// `ref.read`, never from a provider a widget watches, or a retry re-uploads
  /// and the second call 409s against the one the first created.
  Future<DriverDocument> uploadDocument({
    required DocumentType type,
    required List<int> bytes,
    required String filename,
    String? documentNumber,
  });

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
      if (_isNotRegistered(e)) {
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
  Future<DriverVerification> myDocuments() async {
    final json = await _api.get('/api/v1/drivers/me/documents');
    return DriverVerification.fromJson(json);
  }

  @override
  Future<DriverDocument> uploadDocument({
    required DocumentType type,
    required List<int> bytes,
    required String filename,
    String? documentNumber,
  }) async {
    final json = await _api.postMultipart(
      '/api/v1/drivers/me/documents',
      fields: {
        'document_type': type.wireValue,
        if (documentNumber != null && documentNumber.isNotEmpty)
          'document_number': documentNumber,
      },
      fileField: 'file',
      bytes: bytes,
      filename: filename,
    );
    return DriverDocument.fromJson(json);
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
