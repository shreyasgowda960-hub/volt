import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../auth/application/auth_providers.dart';
import '../data/booking_repository.dart';
import '../data/fare_estimator.dart';
import '../data/remote_fare_estimator.dart';
import '../domain/booking.dart';
import '../domain/fare_estimate.dart';
import '../domain/location.dart';
import '../domain/vehicle_type.dart';

// Pickup/drop and the chosen vehicle need to survive navigation across three
// screens, so they live in Riverpod rather than screen-local setState.
class PickupLocationNotifier extends Notifier<Location?> {
  @override
  Location? build() => null;

  void select(Location? location) => state = location;
}

final pickupLocationProvider =
    NotifierProvider<PickupLocationNotifier, Location?>(
        PickupLocationNotifier.new);

class DropLocationNotifier extends Notifier<Location?> {
  @override
  Location? build() => null;

  void select(Location? location) => state = location;
}

final dropLocationProvider =
    NotifierProvider<DropLocationNotifier, Location?>(DropLocationNotifier.new);

class SelectedVehicleNotifier extends Notifier<VehicleType?> {
  @override
  VehicleType? build() => null;

  void select(VehicleType? vehicleType) => state = vehicleType;
}

final selectedVehicleProvider =
    NotifierProvider<SelectedVehicleNotifier, VehicleType?>(
        SelectedVehicleNotifier.new);

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(tokenProvider: ref.watch(authTokenProvider));
});

// Swapped from LocalFareEstimator. The local one stays for offline/tests.
final fareEstimatorProvider = Provider<FareEstimator>((ref) {
  return RemoteFareEstimator(ref.watch(apiClientProvider));
});

final bookingRepositoryProvider = Provider<BookingRepository>((ref) {
  return RemoteBookingRepository(ref.watch(apiClientProvider));
});

final fareEstimatesProvider = FutureProvider.family<List<FareEstimate>, double>(
  (ref, approxWeightKg) async {
    final pickup = ref.watch(pickupLocationProvider);
    final drop = ref.watch(dropLocationProvider);
    if (pickup == null || drop == null) return const [];
    return ref.watch(fareEstimatorProvider).estimateAll(
          pickup,
          drop,
          approxWeightKg: approxWeightKg,
        );
  },
  // Explicit rather than Riverpod's default (10 attempts, up to 6.4s apart):
  // that ceiling leaves the manual Retry button racing an invisible
  // background retry for up to ~38s. 3 attempts total, same backoff shape,
  // gives up quickly enough that Retry is the only thing the user is
  // actually waiting on.
  retry: (retryCount, error) =>
      ProviderContainer.defaultRetry(retryCount, error, maxRetries: 2),
);

final bookingByCodeProvider =
    FutureProvider.family<Booking, String>((ref, publicCode) async {
  return ref.watch(bookingRepositoryProvider).byPublicCode(publicCode);
});
