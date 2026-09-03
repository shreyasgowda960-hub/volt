import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../application/booking_providers.dart';
import '../domain/fare_estimate.dart';
import '../domain/place.dart';
import '../domain/vehicle_type.dart';
import 'booking_status_screen.dart';

class VehicleSelectScreen extends ConsumerStatefulWidget {
  const VehicleSelectScreen({
    required this.goodsDescription,
    required this.approxWeightKg,
    super.key,
  });

  final String goodsDescription;
  final double approxWeightKg;

  @override
  ConsumerState<VehicleSelectScreen> createState() =>
      _VehicleSelectScreenState();
}

class _VehicleSelectScreenState extends ConsumerState<VehicleSelectScreen> {
  bool _booking = false;

  Future<void> _confirm(Place pickup, Place drop, VehicleType vehicleType) async {
    if (_booking) return;
    setState(() => _booking = true);
    try {
      // Must stay a ref.read() call inside this handler, never a
      // FutureProvider watched from build(). A FutureProvider that throws
      // gets Riverpod's automatic retry — silently POSTing a second (or
      // third) booking for the same tap, with no idempotency key on the
      // server to collapse them into one.
      final booking = await ref.read(bookingRepositoryProvider).create(
            pickup: pickup,
            drop: drop,
            vehicleType: vehicleType,
            goodsDescription: widget.goodsDescription,
            approxWeightKg: widget.approxWeightKg,
          );
      if (!mounted) return;
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => BookingStatusScreen(publicCode: booking.publicCode),
        ),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.isUnauthorized) {
        await ref.read(sessionProvider.notifier).signOut();
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _booking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final pickup = ref.watch(pickupLocationProvider);
    final drop = ref.watch(dropLocationProvider);
    final estimates = ref.watch(fareEstimatesProvider(widget.approxWeightKg));
    final selected = ref.watch(selectedVehicleProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Choose a vehicle')),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: estimates.when(
                // Default skipLoadingOnRefresh:true would keep showing the
                // stale error/Retry button for the whole refetch — including
                // a 30-60s Render cold start — with zero feedback. Force the
                // loading branch (and _EstimatesLoadingIndicator's timer) to
                // actually re-mount on every manual Retry tap.
                skipLoadingOnRefresh: false,
                loading: () => const _EstimatesLoadingIndicator(),
                error: (error, _) => Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          error is ApiException
                              ? error.message
                              : 'Something went wrong.',
                          style: const TextStyle(color: AppColors.textSecondary),
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 16),
                        FilledButton(
                          onPressed: () => ref.invalidate(
                              fareEstimatesProvider(widget.approxWeightKg)),
                          child: const Text('Retry'),
                        ),
                      ],
                    ),
                  ),
                ),
                data: (data) => data.isEmpty
                    ? Center(
                        child: Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(
                            pickup == null || drop == null
                                ? 'Select a pickup and drop first'
                                : 'No vehicle can carry ${widget.approxWeightKg.toStringAsFixed(1)} kg on this route. '
                                    'Try splitting the shipment into a lighter load.',
                            style: const TextStyle(color: AppColors.textSecondary),
                            textAlign: TextAlign.center,
                          ),
                        ),
                      )
                    : ListView.separated(
                        padding: const EdgeInsets.all(24),
                        itemCount: data.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 12),
                        itemBuilder: (context, i) {
                          final estimate = data[i];
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
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: FilledButton(
                onPressed: selected == null || pickup == null || drop == null || _booking
                    ? null
                    : () => _confirm(pickup, drop, selected),
                child: _booking
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Confirm booking'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EstimatesLoadingIndicator extends StatefulWidget {
  const _EstimatesLoadingIndicator();

  @override
  State<_EstimatesLoadingIndicator> createState() =>
      _EstimatesLoadingIndicatorState();
}

class _EstimatesLoadingIndicatorState extends State<_EstimatesLoadingIndicator> {
  bool _showWakingMessage = false;
  Timer? _wakingMessageTimer;

  @override
  void initState() {
    super.initState();
    if (AppConfig.isRemote) {
      _wakingMessageTimer = Timer(const Duration(seconds: 5), () {
        setState(() => _showWakingMessage = true);
      });
    }
  }

  @override
  void dispose() {
    _wakingMessageTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(),
          if (_showWakingMessage) ...[
            const SizedBox(height: 16),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 24),
              child: Text(
                'Waking up the server, this can take a minute on the first request.',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
                textAlign: TextAlign.center,
              ),
            ),
          ],
        ],
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
