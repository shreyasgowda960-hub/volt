import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/fare_estimator.dart';
import '../domain/booking_status.dart';
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

final fareEstimatorProvider = Provider((ref) => FareEstimator());

final fareEstimatesProvider = Provider<List<FareEstimate>>((ref) {
  final pickup = ref.watch(pickupLocationProvider);
  final drop = ref.watch(dropLocationProvider);
  if (pickup == null || drop == null) return const [];
  return ref.read(fareEstimatorProvider).estimateAll(pickup, drop);
});

class BookingStatusNotifier extends Notifier<BookingStatus> {
  static const _fakeDrivers = [
    AssignedDriver(name: 'Ravi Kumar', vehicleNumber: 'KA 05 AB 1234', rating: 4.8),
    AssignedDriver(name: 'Suresh Babu', vehicleNumber: 'KA 03 CD 5678', rating: 4.6),
    AssignedDriver(name: 'Manjunath R', vehicleNumber: 'KA 41 EF 9012', rating: 4.9),
  ];

  int _driverIndex = 0;

  @override
  BookingStatus build() => BookingStatus.searching;

  AssignedDriver get assignedDriver => _fakeDrivers[_driverIndex];

  /// Steps through the lifecycle on fixed delays, standing in for FCM/socket
  /// driven status updates from the backend.
  Future<void> start() async {
    _driverIndex = DateTime.now().millisecond % _fakeDrivers.length;
    state = BookingStatus.searching;

    await Future<void>.delayed(const Duration(seconds: 3));
    state = BookingStatus.driverAssigned;

    await Future<void>.delayed(const Duration(seconds: 4));
    state = BookingStatus.pickedUp;

    await Future<void>.delayed(const Duration(seconds: 4));
    state = BookingStatus.delivered;
  }
}

final bookingStatusProvider =
    NotifierProvider<BookingStatusNotifier, BookingStatus>(
        BookingStatusNotifier.new);
