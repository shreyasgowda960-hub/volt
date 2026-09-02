import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../../driver/application/driver_providers.dart';
import '../application/job_watchers.dart';
import '../domain/job.dart';

/// No customer phone number on this screen, and none coming.
///
/// BookingResponse carries no customer contact details by design (spec 011):
/// the customer can call the driver, not the other way round. That asymmetry
/// is enforced server-side and tested there. A driver who genuinely cannot
/// complete a delivery is a support case, which is a real product gap — but
/// not one to paper over with a phone number here.
class ActiveJobScreen extends ConsumerStatefulWidget {
  const ActiveJobScreen({super.key});

  @override
  ConsumerState<ActiveJobScreen> createState() => _ActiveJobScreenState();
}

class _ActiveJobScreenState extends ConsumerState<ActiveJobScreen> {
  bool _working = false;
  String? _error;
  bool _announcedCancellation = false;

  Future<bool> _confirm(String title) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Confirm')),
        ],
      ),
    );
    return result ?? false;
  }

  Future<void> _advance(
    String title,
    Future<Job> Function(String code) action, {
    required String code,
    bool popOnSuccess = false,
    String? successMessage,
  }) async {
    if (!await _confirm(title)) return;
    setState(() {
      _working = true;
      _error = null;
    });
    try {
      // ref.read in a handler — these mutate. Riverpod's auto-retry on a
      // watched provider would re-POST a pickup or a delivery.
      final updated = await action(code);
      if (!mounted) return;
      // Push it into the watcher so the screen moves now rather than on the
      // next 5s tick, and so a terminal status stops the poller.
      ref.read(activeJobWatcherProvider.notifier).applyLocalUpdate(updated);
      if (popOnSuccess) {
        if (successMessage != null) {
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text(successMessage)));
        }
        Navigator.of(context).pop();
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  /// The reason this screen polls at all: the customer can cancel while the
  /// driver is already on the way, and driving to a pickup that no longer
  /// exists is the worst thing the system can do to a driver. Announce it and
  /// get them back to the board.
  void _handleCancellation(Job job) {
    if (_announcedCancellation) return;
    _announcedCancellation = true;
    // After the current frame: this runs from build(), and both showDialog
    // and pop mutate the navigator.
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Booking cancelled'),
          content: Text(
            'The customer cancelled ${job.publicCode}. Do not continue to '
            'the pickup.',
          ),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Back to jobs'),
            ),
          ],
        ),
      );
      if (!mounted) return;
      Navigator.of(context).pop();
    });
  }

  @override
  Widget build(BuildContext context) {
    final jobAsync = ref.watch(activeJobWatcherProvider);

    return Scaffold(
      appBar: AppBar(title: Text(jobAsync.value?.publicCode ?? 'Job')),
      body: SafeArea(
        child: jobAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                error is ApiException
                    ? error.message
                    : 'Something went wrong.',
                style: const TextStyle(color: AppColors.textSecondary),
                textAlign: TextAlign.center,
              ),
            ),
          ),
          data: (job) {
            if (job == null) {
              // Nothing assigned any more and no status to explain it.
              return const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Text(
                    'This job is no longer assigned to you.',
                    style: TextStyle(color: AppColors.textSecondary),
                    textAlign: TextAlign.center,
                  ),
                ),
              );
            }
            if (job.status == JobStatus.cancelled) {
              _handleCancellation(job);
            }
            return _JobBody(
              job: job,
              working: _working,
              error: _error,
              onPickedUp: () => _advance(
                'Confirm pickup?',
                ref.read(driverRepositoryProvider).markPickedUp,
                code: job.publicCode,
              ),
              onDelivered: () => _advance(
                'Confirm delivery?',
                ref.read(driverRepositoryProvider).markDelivered,
                code: job.publicCode,
                popOnSuccess: true,
                successMessage: 'Delivered',
              ),
            );
          },
        ),
      ),
    );
  }
}

class _JobBody extends StatelessWidget {
  const _JobBody({
    required this.job,
    required this.working,
    required this.error,
    required this.onPickedUp,
    required this.onDelivered,
  });

  final Job job;
  final bool working;
  final String? error;
  final VoidCallback onPickedUp;
  final VoidCallback onDelivered;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '₹${job.quotedFareInr.round()}',
            style: const TextStyle(
                fontWeight: FontWeight.w700,
                fontSize: 28,
                color: AppColors.navy),
          ),
          const SizedBox(height: 20),
          _InfoRow(
              icon: Icons.trip_origin,
              label: 'Pickup',
              value: job.pickupAddress),
          const SizedBox(height: 12),
          _InfoRow(
              icon: Icons.location_on_outlined,
              label: 'Drop',
              value: job.dropAddress),
          const SizedBox(height: 12),
          _InfoRow(
              icon: Icons.inventory_2_outlined,
              label: 'Goods',
              value: job.goodsDescription),
          const SizedBox(height: 12),
          _InfoRow(
              icon: Icons.scale_outlined,
              label: 'Weight',
              value: '${job.approxWeightKg}kg'),
          if (error != null) ...[
            const SizedBox(height: 16),
            Text(error!,
                style:
                    const TextStyle(color: AppColors.danger, fontSize: 13)),
          ],
          const Spacer(),
          if (job.status == JobStatus.driverAssigned)
            FilledButton(
              onPressed: working ? null : onPickedUp,
              child: working ? _spinner() : const Text('Picked up'),
            )
          else if (job.status == JobStatus.pickedUp)
            FilledButton(
              onPressed: working ? null : onDelivered,
              child: working ? _spinner() : const Text('Delivered'),
            ),
        ],
      ),
    );
  }

  Widget _spinner() => const SizedBox(
        height: 22,
        width: 22,
        child:
            CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
      );
}

class _InfoRow extends StatelessWidget {
  const _InfoRow(
      {required this.icon, required this.label, required this.value});

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, color: AppColors.navy, size: 20),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label,
                  style: const TextStyle(
                      color: AppColors.textSecondary, fontSize: 12)),
              Text(value,
                  style: const TextStyle(fontWeight: FontWeight.w500)),
            ],
          ),
        ),
      ],
    );
  }
}
