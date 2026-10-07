import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../../driver/application/driver_providers.dart';

/// Both documents are in and a human has not looked yet.
///
/// NO SPINNER and NO POLLING, both deliberate. A spinner implies something is
/// happening right now; what is actually happening is that a person will open
/// a queue later. And a review takes hours, so a 5-second poll would be
/// thousands of requests to watch a field that changes once — the booking
/// poller exists because a job board changes by the minute, which this does
/// not. Pull to refresh is the whole interaction.
class PendingReviewScreen extends ConsumerWidget {
  const PendingReviewScreen({super.key});

  /// Swallows the failure on purpose, and tells the driver about it instead.
  ///
  /// Two reasons. An uncaught rejection here is an unhandled async error, and
  /// _ProfileGate already keeps the last good state through a failed refresh —
  /// so without a message the pull would spin, stop, and look like "still
  /// nothing", which is indistinguishable from a successful check that found
  /// no change.
  Future<void> _refresh(BuildContext context, WidgetRef ref) async {
    try {
      // invalidate + read rather than refresh(): same effect, and refresh()
      // is @useResult, which it is not here — the value is routed on by
      // _ProfileGate, not consumed in this handler.
      ref.invalidate(driverProfileProvider);
      await ref.read(driverProfileProvider.future);
    } catch (_) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not check just now.')),
      );
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Under review'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(sessionProvider.notifier).signOut(),
          ),
        ],
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () => _refresh(context, ref),
          // AlwaysScrollable so the gesture exists even though the content is
          // shorter than the screen — without it there is nothing to pull.
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.xl,
              vertical: AppSpacing.xxl,
            ),
            children: const [
              Icon(
                Icons.assignment_turned_in_outlined,
                size: 56,
                color: AppColors.navy,
              ),
              SizedBox(height: AppSpacing.xl),
              Text(
                'Your documents are with us',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              SizedBox(height: AppSpacing.md),
              Text(
                'Someone checks every driver by hand before the first job. '
                'This usually takes a day. We will let you know either way, '
                'and if anything needs redoing you will be able to send it '
                'again from here.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textSecondary, height: 1.45),
              ),
              SizedBox(height: AppSpacing.xxl),
              Text(
                'Pull down to check for an update.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textDisabled, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
