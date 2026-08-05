import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../application/booking_providers.dart';
import '../domain/fare_estimate.dart';
import '../domain/vehicle_type.dart';
import 'booking_status_screen.dart';

class VehicleSelectScreen extends ConsumerWidget {
  const VehicleSelectScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final estimates = ref.watch(fareEstimatesProvider);
    final selected = ref.watch(selectedVehicleProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Choose a vehicle')),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: estimates.isEmpty
                  ? const Center(
                      child: Text(
                        'Select a pickup and drop first',
                        style: TextStyle(color: AppColors.textSecondary),
                      ),
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.all(24),
                      itemCount: estimates.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 12),
                      itemBuilder: (context, i) {
                        final estimate = estimates[i];
                        return _VehicleCard(
                          estimate: estimate,
                          selected: selected == estimate.vehicleType,
                          onTap: () => ref
                              .read(selectedVehicleProvider.notifier)
                              .select(estimate.vehicleType),
                        );
                      },
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: FilledButton(
                onPressed: selected == null
                    ? null
                    : () {
                        // Fire-and-forget: the ~11s lifecycle plays out on
                        // BookingStatusScreen, which watches the same state.
                        ref.read(bookingStatusProvider.notifier).start();
                        Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => const BookingStatusScreen(),
                          ),
                        );
                      },
                child: const Text('Confirm booking'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _VehicleCard extends StatelessWidget {
  const _VehicleCard({
    required this.estimate,
    required this.selected,
    required this.onTap,
  });

  final FareEstimate estimate;
  final bool selected;
  final VoidCallback onTap;

  IconData _iconFor(VehicleType type) {
    switch (type) {
      case VehicleType.bike:
        return Icons.two_wheeler;
      case VehicleType.threeWheeler:
        return Icons.electric_rickshaw;
      case VehicleType.miniTruck:
        return Icons.local_shipping;
    }
  }

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          color: selected ? AppColors.navy.withValues(alpha: 0.06) : Colors.white,
          border: Border.all(
            color: selected ? AppColors.navy : AppColors.border,
            width: selected ? 2 : 1,
          ),
        ),
        child: Row(
          children: [
            Icon(_iconFor(estimate.vehicleType), color: AppColors.navy, size: 32),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    estimate.vehicleType.label,
                    style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 16),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${estimate.distanceKm.toStringAsFixed(1)} km · ${estimate.etaMinutes} min',
                    style: const TextStyle(color: AppColors.textSecondary, fontSize: 13),
                  ),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  '₹${estimate.fareInr.round()}',
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 18,
                    color: AppColors.navy,
                  ),
                ),
                if (selected) ...[
                  const SizedBox(height: 4),
                  const Icon(Icons.check_circle, color: AppColors.navy, size: 20),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
}
