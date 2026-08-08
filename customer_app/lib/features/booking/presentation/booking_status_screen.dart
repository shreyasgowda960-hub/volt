import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/theme/app_colors.dart';
import '../application/booking_providers.dart';
import '../domain/booking.dart';
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
  const BookingStatusScreen({required this.publicCode, super.key});

  final String publicCode;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final booking = ref.watch(bookingByCodeProvider(publicCode));

    return Scaffold(
      appBar: AppBar(
        title: const Text('Booking status'),
        automaticallyImplyLeading: false,
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(bookingByCodeProvider(publicCode)),
          ),
        ],
      ),
      body: SafeArea(
        child: booking.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    error is ApiException ? error.message : 'Something went wrong.',
                    style: const TextStyle(color: AppColors.textSecondary),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: () => ref.invalidate(bookingByCodeProvider(publicCode)),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
          ),
          data: (data) => _BookingStatusBody(booking: data),
        ),
      ),
    );
  }
}

class _BookingStatusBody extends StatelessWidget {
  const _BookingStatusBody({required this.booking});

  final Booking booking;

  @override
  Widget build(BuildContext context) {
    final status = booking.status;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 16),
            const Text(
              'Tracking your delivery',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 4),
            Text(
              booking.publicCode,
              style: const TextStyle(
                color: AppColors.textSecondary,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.5,
              ),
            ),
            const SizedBox(height: 28),
            for (var i = 0; i < _steps.length; i++)
              _StepRow(
                index: i,
                label: _steps[i],
                state: _stateFor(i, status),
                isLast: i == _steps.length - 1,
              ),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.border),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(booking.goodsDescription,
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text('${booking.pickupAddress} → ${booking.dropAddress}',
                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 13)),
                  const SizedBox(height: 8),
                  Text(
                    '₹${booking.quotedFareInr.round()}',
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 18,
                      color: AppColors.navy,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
          ],
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
