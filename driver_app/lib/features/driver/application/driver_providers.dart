import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../data/driver_repository.dart';
import '../domain/driver_profile.dart';
import '../domain/vehicle_type_option.dart';

// volt_core doesn't expose an ApiClient provider (customer_app builds its
// own the same way) — constructed from authTokenProvider per spec.
final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(tokenProvider: ref.watch(authTokenProvider));
});

final driverRepositoryProvider = Provider<DriverRepository>((ref) {
  return RemoteDriverRepository(ref.watch(apiClientProvider));
});

final vehicleTypesProvider = FutureProvider<List<VehicleTypeOption>>((ref) async {
  return ref.watch(driverRepositoryProvider).vehicleTypes();
});

/// Null when the caller has no driver record yet — a routing signal, not an
/// error. DriverNotRegistered is caught here rather than left to become an
/// AsyncError state that main.dart would have to unpack.
final driverProfileProvider = FutureProvider<DriverProfile?>((ref) async {
  try {
    return await ref.watch(driverRepositoryProvider).me();
  } on DriverNotRegistered {
    return null;
  }
});

// availableJobsProvider and activeJobProvider lived here until spec 011.
// Both are now polling notifiers in
// features/jobs/application/job_watchers.dart — jobBoardWatcherProvider and
// activeJobWatcherProvider — because a one-shot fetch cannot notice a job
// appearing on the board, or a customer cancelling while the driver drives.
