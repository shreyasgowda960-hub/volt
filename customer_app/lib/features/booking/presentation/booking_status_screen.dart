import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../application/booking_providers.dart';
import '../domain/booking_status.dart';

const _steps = ['Finding a driver', 'Driver assigned', 'Picked up', 'Delivered'];

enum _StepState { done, current, upcoming }

_StepState _stateFor(int i, BookingStatus status) {
  final currentIndex = status.index;
  if (i < currentIndex) return _StepState.done;
  if (i == currentIndex) {
    return status == BookingStatus.delivered ? _StepState.done : _StepState.current;
  }
  return _StepState.upcoming;
}

class BookingStatusScreen extends ConsumerWidget {
  const BookingStatusScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(bookingStatusProvider);
    final driver = ref.read(bookingStatusProvider.notifier).assignedDriver;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Booking status'),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 16),
              const Text(
                'Tracking your delivery',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 28),
              for (var i = 0; i < _steps.length; i++)
                _StepRow(
                  index: i,
                  label: _steps[i],
                  state: _stateFor(i, status),
                  isLast: i == _steps.length - 1,
                ),
              if (status.index >= BookingStatus.driverAssigned.index) ...[
                const SizedBox(height: 24),
                _DriverCard(driver: driver),
              ],
              const Spacer(),
              if (status == BookingStatus.delivered)
                FilledButton(
                  onPressed: () {
                    ref.read(pickupLocationProvider.notifier).select(null);
                    ref.read(dropLocationProvider.notifier).select(null);
                    ref.read(selectedVehicleProvider.notifier).select(null);
                    Navigator.of(context).popUntil((route) => route.isFirst);
                  },
                  child: const Text('Book another'),
                ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({
    required this.index,
    required this.label,
    required this.state,
    required this.isLast,
  });

  final int index;
  final String label;
  final _StepState state;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final done = state == _StepState.done;
    final current = state == _StepState.current;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Column(
          children: [
            Container(
              width: 28,
              height: 28,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: done ? AppColors.navy : Colors.white,
                border: Border.all(
                  color: done || current ? AppColors.navy : AppColors.border,
                  width: current ? 2 : 1,
                ),
              ),
              child: Center(
                child: done
                    ? const Icon(Icons.check, size: 16, color: Colors.white)
                    : current
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: AppColors.navy,
                            ),
                          )
                        : Text(
                            '${index + 1}',
                            style: const TextStyle(
                              color: AppColors.textSecondary,
                              fontSize: 12,
                            ),
                          ),
              ),
            ),
            if (!isLast)
              Container(
                width: 2,
                height: 36,
                color: done ? AppColors.navy : AppColors.border,
              ),
          ],
        ),
        const SizedBox(width: 16),
        Padding(
          padding: EdgeInsets.only(top: 4, bottom: isLast ? 0 : 28),
          child: Text(
            label,
            style: TextStyle(
              fontWeight: state == _StepState.upcoming ? FontWeight.w400 : FontWeight.w600,
              color: state == _StepState.upcoming ? AppColors.textSecondary : AppColors.navy,
            ),
          ),
        ),
      ],
    );
  }
}

class _DriverCard extends StatelessWidget {
  const _DriverCard({required this.driver});

  final AssignedDriver driver;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          const CircleAvatar(
            backgroundColor: AppColors.surface,
            child: Icon(Icons.person, color: AppColors.navy),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(driver.name, style: const TextStyle(fontWeight: FontWeight.w600)),
                Text(
                  driver.vehicleNumber,
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 13),
                ),
              ],
            ),
          ),
          Row(
            children: [
              const Icon(Icons.star, color: AppColors.yellow, size: 18),
              const SizedBox(width: 4),
              Text(
                driver.rating.toStringAsFixed(1),
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
