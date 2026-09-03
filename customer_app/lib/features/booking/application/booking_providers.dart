import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import 'dart:math';

import '../data/booking_repository.dart';
import '../data/fare_estimator.dart';
import '../data/places_service.dart';
import '../data/remote_fare_estimator.dart';
import '../domain/fare_estimate.dart';
import '../domain/place.dart';
import '../domain/vehicle_type.dart';

// Pickup/drop and the chosen vehicle need to survive navigation across three
// screens, so they live in Riverpod rather than screen-local setState.
class PickupLocationNotifier extends Notifier<Place?> {
  @override
  Place? build() => null;

  void select(Place? place) => state = place;
}

final pickupLocationProvider =
    NotifierProvider<PickupLocationNotifier, Place?>(
        PickupLocationNotifier.new);

class DropLocationNotifier extends Notifier<Place?> {
  @override
  Place? build() => null;

  void select(Place? place) => state = place;
}

final dropLocationProvider =
    NotifierProvider<DropLocationNotifier, Place?>(DropLocationNotifier.new);

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

final placesServiceProvider = Provider<PlacesService>((ref) {
  return RemotePlacesService(ref.watch(apiClientProvider));
});

/// Fetched once and kept for the session. Three separate things need it —
/// where to centre the map, where to bias autocomplete, and what to
/// pre-check before submitting — and it changes only when someone edits an
/// environment variable on the server.
///
/// keepAlive because this is the rare case that actually wants it: refetching
/// a value that changes monthly, every time the picker opens, would be a
/// wasted round trip on a sleeping free-tier backend.
final serviceAreaProvider = FutureProvider<ServiceArea>((ref) async {
  return ref.watch(placesServiceProvider).serviceArea();
}, isAutoDispose: false);

/// Straight-line distance from the service centre, in km.
///
/// Mirrors the server's check — same haversine, same comparison — so the app
/// can say "that is outside our area" instantly instead of after a round
/// trip. The server still enforces it: this is UX, that is the rule. A
/// patched client can send anything.
double distanceFromCentreKm(ServiceArea area, double lat, double lng) {
  const earthRadiusKm = 6371.0;
  double toRad(double deg) => deg * (pi / 180);

  final dLat = toRad(lat - area.centerLat);
  final dLng = toRad(lng - area.centerLng);
  final h = sin(dLat / 2) * sin(dLat / 2) +
      cos(toRad(area.centerLat)) * cos(toRad(lat)) * sin(dLng / 2) * sin(dLng / 2);
  return earthRadiusKm * 2 * atan2(sqrt(h), sqrt(1 - h));
}

/// Null when the point is serviceable, otherwise the message to show.
///
/// The boundary is inclusive, matching the server's `>` comparison — a
/// location exactly on the radius is inside, and the two must agree or the
/// app blocks something the server would accept.
String? serviceAreaRejection(ServiceArea area, double lat, double lng) {
  final km = distanceFromCentreKm(area, lat, lng);
  if (km <= area.radiusKm) return null;
  return 'That location is ${km.round()}km from the city centre. '
      'We currently deliver within ${area.radiusKm.round()}km.';
}

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

// bookingByCodeProvider lived here until spec 011. Replaced by
// bookingWatcherProvider in booking_watcher.dart — a one-shot fetch behind a
// manual refresh button was the whole thing this spec set out to remove.
// Deleted rather than kept alongside: two ways to read the same booking, one
// of which silently never updates, is a trap for whoever wires up the next
// screen.
