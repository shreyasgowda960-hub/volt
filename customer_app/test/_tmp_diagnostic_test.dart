import 'package:customer_app/features/booking/application/booking_providers.dart';
import 'package:customer_app/features/booking/data/fare_estimator.dart';
import 'package:customer_app/features/booking/domain/fare_estimate.dart';
import 'package:customer_app/features/booking/domain/location.dart';
import 'package:customer_app/features/booking/domain/vehicle_type.dart';
import 'package:customer_app/features/booking/presentation/vehicle_select_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _FixedPickup extends PickupLocationNotifier {
  @override
  Location? build() => const Location(name: 'A', lat: 12.9, lng: 77.6);
}

class _FixedDrop extends DropLocationNotifier {
  @override
  Location? build() => const Location(name: 'B', lat: 12.8, lng: 77.7);
}

class _FlakyEstimator implements FareEstimator {
  int calls = 0;

  @override
  Future<List<FareEstimate>> estimateAll(
    Location pickup,
    Location drop, {
    required double approxWeightKg,
  }) async {
    calls++;
    if (calls == 1) {
      throw Exception('boom');
    }
    return [
      const FareEstimate(
        vehicleType: VehicleType.bike,
        distanceKm: 5,
        fareInr: 40,
        etaMinutes: 10,
      ),
    ];
  }
}

void main() {
  testWidgets('loading indicator after Retry from an error', (tester) async {
    final estimator = _FlakyEstimator();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          pickupLocationProvider.overrideWith(_FixedPickup.new),
          dropLocationProvider.overrideWith(_FixedDrop.new),
          fareEstimatorProvider.overrideWithValue(estimator),
        ],
        child: const MaterialApp(
          home: VehicleSelectScreen(goodsDescription: 'x', approxWeightKg: 5),
        ),
      ),
    );

    // Let the first (failing) estimateAll call resolve.
    debugPrint('calls right after pumpWidget: ${estimator.calls}');
    await tester.pump();
    debugPrint('calls after pump 1: ${estimator.calls}');
    await tester.pump();
    debugPrint('calls after pump 2: ${estimator.calls}');
    await tester.pump(const Duration(milliseconds: 500));
    debugPrint('calls after pump 3 (500ms): ${estimator.calls}');

    debugPrint('--- after first failure ---');
    final texts = find.byType(Text).evaluate().map((e) => (e.widget as Text).data).toList();
    debugPrint('All text widgets: $texts');
    debugPrint('Exception during pump: ${tester.takeException()}');
    debugPrint('Retry button present: ${find.text('Retry').evaluate().isNotEmpty}');

    await tester.tap(find.text('Retry'));
    await tester.pump();

    debugPrint('--- immediately after tapping Retry ---');
    debugPrint(
        'CircularProgressIndicator present: ${find.byType(CircularProgressIndicator).evaluate().isNotEmpty}');
    debugPrint('Retry button still present: ${find.text('Retry').evaluate().isNotEmpty}');
    debugPrint(
        'Waking-up message present: ${find.textContaining('Waking up').evaluate().isNotEmpty}');

    // Advance past the 5s mark without letting the second call resolve
    // (it resolves near-instantly in this fake, so we check state frame-by-frame).
    await tester.pump(const Duration(milliseconds: 10));
    debugPrint('--- 10ms after retry tap ---');
    debugPrint(
        'CircularProgressIndicator present: ${find.byType(CircularProgressIndicator).evaluate().isNotEmpty}');
    debugPrint('Data card present: ${find.text('Bike').evaluate().isNotEmpty}');
  });
}
