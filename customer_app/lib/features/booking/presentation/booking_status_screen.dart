import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:volt_core/volt_core.dart';

import '../application/booking_providers.dart';
import '../application/booking_watcher.dart';
import '../domain/assigned_driver.dart';
import '../domain/booking.dart';
import '../domain/booking_status.dart';

/// The four steps a booking walks through, in order. Terminal failures
/// (cancelled, expired) are deliberately not steps — they replace the
/// timeline rather than extend it.
const _steps = ['Booking placed', 'Driver assigned', 'Picked up', 'Delivered'];

enum _StepState { done, current, upcoming }

/// Explicitly mapped, never `status.index`.
///
/// The old version compared step position against the enum's index, which
/// worked only while the enum happened to be exactly the four progress values
/// in exactly the right order. Adding `cancelled` and `expired` — which have
/// indices 4 and 5 and no place on this timeline at all — would have marked
/// every step complete on an expired booking.
_StepState _stateFor(int stepIndex, Booking booking) {
  final reached = switch (booking.status) {
    BookingStatus.pending => 0,
    BookingStatus.driverAssigned => 1,
    BookingStatus.pickedUp => 2,
    BookingStatus.delivered => 3,
    // Not rendered — the terminal panels replace the timeline — but mapped
    // rather than left to a default so a future status cannot silently
    // inherit someone else's position.
    BookingStatus.cancelled || BookingStatus.expired => 0,
  };

  if (stepIndex < reached) return _StepState.done;
  if (stepIndex > reached) return _StepState.upcoming;
  return booking.status == BookingStatus.delivered
      ? _StepState.done
      : _StepState.current;
}

DateTime? _timeFor(int stepIndex, Booking booking) => switch (stepIndex) {
      0 => booking.createdAt.toLocal(),
      1 => booking.driverAssignedAt,
      2 => booking.pickedUpAt,
      3 => booking.deliveredAt,
      _ => null,
    };

String _clock(DateTime time) {
  final hour = time.hour % 12 == 0 ? 12 : time.hour % 12;
  final minute = time.minute.toString().padLeft(2, '0');
  return '$hour:$minute ${time.hour < 12 ? 'am' : 'pm'}';
}

class BookingStatusScreen extends ConsumerStatefulWidget {
  const BookingStatusScreen({required this.publicCode, super.key});

  final String publicCode;

  @override
  ConsumerState<BookingStatusScreen> createState() =>
      _BookingStatusScreenState();
}

class _BookingStatusScreenState extends ConsumerState<BookingStatusScreen> {
  bool _cancelling = false;

  Future<void> _call(String phone) async {
    final uri = Uri(scheme: 'tel', path: phone);
    // canLaunchUrl needs the <queries> tel entry in AndroidManifest.xml or it
    // returns false on API 30+ regardless of whether a dialler exists.
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
      return;
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('No dialler available on this device')),
    );
  }

  /// Same guard, same reason as the driver app's pickup and deliver buttons:
  /// the flag is taken before the dialog opens, not after it resolves. With
  /// it taken afterwards, the Cancel button stays enabled for the dialog's
  /// dismissal animation and a tap in that window sends a second cancel.
  Future<void> _cancel() async {
    if (_cancelling) return;
    setState(() => _cancelling = true);

    try {
      var answered = false;
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Cancel this booking?'),
          // No fee messaging: cancellation is free before pickup (phase 1
          // decision), and inventing a warning would imply otherwise.
          content: const Text(
            "You won't be charged. If a driver is already assigned, they'll "
            'be released to take other jobs.',
          ),
          actions: [
            TextButton(
              onPressed: () {
                if (answered) return;
                answered = true;
                Navigator.pop(dialogContext, false);
              },
              child: const Text('Keep booking'),
            ),
            FilledButton(
              onPressed: () {
                // Latched: a double-tap here would pop the dialog and then
                // pop the status screen itself.
                if (answered) return;
                answered = true;
                Navigator.pop(dialogContext, true);
              },
              child: const Text('Cancel booking'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;

      // ref.read in a handler, never a watched provider: this mutates. A
      // FutureProvider would hand it Riverpod's auto-retry, and a retried
      // cancel on a booking a driver has since picked up would 409 in a loop.
      await ref.read(bookingRepositoryProvider).cancel(widget.publicCode);
      // No local state update needed — the watcher's next poll picks up
      // `cancelled` on its own, which is also what proves polling works.
      await ref
          .read(bookingWatcherProvider(widget.publicCode).notifier)
          .refreshNow();
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _cancelling = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final watched = ref.watch(bookingWatcherProvider(widget.publicCode));
    final notifier =
        ref.read(bookingWatcherProvider(widget.publicCode).notifier);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Booking status'),
        automaticallyImplyLeading: false,
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            // Kept deliberately. Polling fails — bad network, a sleeping free
            // tier — and when it does this is the customer's only recourse.
            onPressed: notifier.refreshNow,
          ),
        ],
      ),
      body: SafeArea(
        child: watched.when(
          // Only the very first load can reach these two branches. Once a
          // booking has arrived, a failed poll leaves the data in place and
          // raises the staleness counter instead.
          loading: () => const Center(child: CircularProgressIndicator()),
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
                        bookingWatcherProvider(widget.publicCode)),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
          ),
          data: (watch) => _Body(
            watch: watch,
            cancelling: _cancelling,
            onCall: _call,
            onCancel: _cancel,
          ),
        ),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({
    required this.watch,
    required this.cancelling,
    required this.onCall,
    required this.onCancel,
  });

  final BookingWatchState watch;
  final bool cancelling;
  final Future<void> Function(String phone) onCall;
  final Future<void> Function() onCancel;

  @override
  Widget build(BuildContext context) {
    final booking = watch.booking;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 16),
            Text(
              switch (booking.status) {
                BookingStatus.delivered => 'Delivered',
                BookingStatus.cancelled => 'Booking cancelled',
                BookingStatus.expired => 'No driver was available',
                _ => 'Tracking your delivery',
              },
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
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
            if (watch.isStale) ...[
              const SizedBox(height: 12),
              const _StaleBanner(),
            ],
            const SizedBox(height: 24),
            switch (booking.status) {
              BookingStatus.expired => const _ExpiredPanel(),
              BookingStatus.cancelled => _CancelledPanel(booking: booking),
              _ => _Timeline(booking: booking),
            },
            if (booking.driver != null) ...[
              const SizedBox(height: 20),
              _DriverCard(driver: booking.driver!, onCall: onCall),
            ],
            const SizedBox(height: 20),
            _BookingSummary(booking: booking),
            if (booking.status.isCancellable) ...[
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton(
                  onPressed: cancelling ? null : onCancel,
                  child: cancelling
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Cancel booking'),
                ),
              ),
            ],
            if (booking.status == BookingStatus.expired) ...[
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  // Back to the still-alive BookingHomeScreen at the root.
                  onPressed: () =>
                      Navigator.of(context).popUntil((r) => r.isFirst),
                  child: const Text('Book again'),
                ),
              ),
            ],
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}

/// Shown after several consecutive failed polls. Says the screen is out of
/// date without implying the booking itself went wrong — the data below is
/// still real, just possibly a minute old.
class _StaleBanner extends StatelessWidget {
  const _StaleBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        color: AppColors.danger.withValues(alpha: 0.08),
      ),
      child: const Row(
        children: [
          Icon(Icons.cloud_off_outlined, size: 16, color: AppColors.danger),
          SizedBox(width: 8),
          Expanded(
            child: Text(
              'Not updating — check your connection',
              style: TextStyle(fontSize: 12, color: AppColors.danger),
            ),
          ),
        ],
      ),
    );
  }
}

class _ExpiredPanel extends StatelessWidget {
  const _ExpiredPanel();

  @override
  Widget build(BuildContext context) {
    // Wording matters here more than anywhere else on the screen: expiry is a
    // supply failure on our side, not a customer error. An apology with a
    // next step, not an error message.
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            "Sorry — we couldn't find a driver for this booking in time.",
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
          SizedBox(height: 6),
          Text(
            "You haven't been charged. Booking again usually works, "
            'especially a few minutes later.',
            style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
          ),
        ],
      ),
    );
  }
}

class _CancelledPanel extends StatelessWidget {
  const _CancelledPanel({required this.booking});

  final Booking booking;

  @override
  Widget build(BuildContext context) {
    final byDriver = booking.cancelledBy == 'driver';
    final bySystem = booking.cancelledBy == 'system';

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            byDriver
                ? 'The driver cancelled this booking.'
                : bySystem
                    ? 'This booking was cancelled by VOLT.'
                    : 'You cancelled this booking.',
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          if (booking.cancellationReason != null) ...[
            const SizedBox(height: 6),
            Text(
              booking.cancellationReason!,
              style: const TextStyle(
                  color: AppColors.textSecondary, fontSize: 13),
            ),
          ],
          if (booking.cancelledAt != null) ...[
            const SizedBox(height: 6),
            Text(
              'Cancelled at ${_clock(booking.cancelledAt!)}',
              style: const TextStyle(
                  color: AppColors.textSecondary, fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }
}

class _Timeline extends StatelessWidget {
  const _Timeline({required this.booking});

  final Booking booking;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < _steps.length; i++)
          _StepRow(
            index: i,
            label: _steps[i],
            time: _timeFor(i, booking),
            state: _stateFor(i, booking),
            isLast: i == _steps.length - 1,
          ),
      ],
    );
  }
}

class _DriverCard extends StatelessWidget {
  const _DriverCard({required this.driver, required this.onCall});

  final AssignedDriver driver;
  final Future<void> Function(String phone) onCall;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        color: AppColors.navy.withValues(alpha: 0.04),
        border: Border.all(color: AppColors.navy.withValues(alpha: 0.2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // The vehicle number is the largest thing on the card on purpose:
          // it is what the customer scans the street for.
          Text(
            driver.vehicleNumber,
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w700,
              letterSpacing: 1,
              color: AppColors.navy,
            ),
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Expanded(
                child: Text(
                  '${driver.name} · ${driver.vehicleTypeCode}',
                  style: const TextStyle(
                      color: AppColors.textSecondary, fontSize: 13),
                ),
              ),
              if (driver.rating != null) ...[
                const Icon(Icons.star, size: 14, color: AppColors.navy),
                const SizedBox(width: 2),
                Text(
                  driver.rating!.toStringAsFixed(1),
                  style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w600),
                ),
              ],
            ],
          ),
          // Absent once the booking is terminal — the server stops sending the
          // number, so there is nothing to call. Not an error state; the trip
          // is simply over.
          if (driver.isCallable) ...[
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: () => onCall(driver.phone!),
                icon: const Icon(Icons.call, size: 18),
                label: const Text('Call driver'),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _BookingSummary extends StatelessWidget {
  const _BookingSummary({required this.booking});

  final Booking booking;

  @override
  Widget build(BuildContext context) {
    final settled = booking.finalFarePaise != null;

    return Container(
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
          Text(
            '${booking.pickupAddress} → ${booking.dropAddress}',
            style:
                const TextStyle(color: AppColors.textSecondary, fontSize: 13),
          ),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '₹${booking.payableFareInr.round()}',
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 18,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(width: 6),
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text(
                  settled ? 'final fare' : 'quoted',
                  style: const TextStyle(
                      color: AppColors.textSecondary, fontSize: 12),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({
    required this.index,
    required this.label,
    required this.time,
    required this.state,
    required this.isLast,
  });

  final int index;
  final String label;
  final DateTime? time;
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
        Expanded(
          child: Padding(
            padding: EdgeInsets.only(top: 4, bottom: isLast ? 0 : 28),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      fontWeight: state == _StepState.upcoming
                          ? FontWeight.w400
                          : FontWeight.w600,
                      color: state == _StepState.upcoming
                          ? AppColors.textSecondary
                          : AppColors.navy,
                    ),
                  ),
                ),
                // Only where the server actually recorded one — a step that
                // has not happened has a NULL timestamp, never a guess.
                if (time != null && (done || current))
                  Text(
                    _clock(time!),
                    style: const TextStyle(
                        color: AppColors.textSecondary, fontSize: 12),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
