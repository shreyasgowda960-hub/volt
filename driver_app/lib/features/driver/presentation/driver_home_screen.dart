import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../../jobs/application/job_watchers.dart';
import '../../jobs/domain/job.dart';
import '../../jobs/presentation/active_job_screen.dart';
import '../application/driver_providers.dart';
import '../data/driver_repository.dart';
import '../domain/driver_profile.dart';

class DriverHomeScreen extends ConsumerStatefulWidget {
  const DriverHomeScreen({super.key});

  @override
  ConsumerState<DriverHomeScreen> createState() => _DriverHomeScreenState();
}

class _DriverHomeScreenState extends ConsumerState<DriverHomeScreen> {
  // Which card is mid-accept, if any. Local UI state — not a provider,
  // because accepting must be a ref.read in the button handler (see below).
  String? _acceptingCode;

  Future<void> _toggleOnline(bool online) async {
    try {
      await ref.read(driverRepositoryProvider).setOnline(online);
      ref.invalidate(driverProfileProvider);
      ref.invalidate(activeJobWatcherProvider);
      if (online) ref.invalidate(jobBoardWatcherProvider);
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _accept(Job job) async {
    setState(() => _acceptingCode = job.publicCode);

    // Deliberately ref.read, not a watched provider: Riverpod 3 auto-retries
    // a failed FutureProvider, and an auto-retried accept would claim a job
    // the driver never chose to accept a second time.
    try {
      final accepted = await ref.read(driverRepositoryProvider).accept(job.publicCode);
      if (!mounted) return;
      setState(() => _acceptingCode = null);
      // Hand the just-claimed job straight to the watcher rather than making
      // it refetch: accept already returned the authoritative row, and this
      // is also what starts it polling for a customer cancellation.
      ref.read(activeJobWatcherProvider.notifier).applyLocalUpdate(accepted);
      await Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const ActiveJobScreen()),
      );
      // Back from delivering (or from an early pop) — either way the active
      // job may have changed, so refresh both.
      ref.invalidate(activeJobWatcherProvider);
      ref.invalidate(jobBoardWatcherProvider);
    } on JobAlreadyClaimed {
      if (!mounted) return;
      setState(() => _acceptingCode = null);
      ref.invalidate(jobBoardWatcherProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Another driver took that job')),
      );
    } on JobExpired {
      if (!mounted) return;
      setState(() => _acceptingCode = null);
      ref.invalidate(jobBoardWatcherProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('That booking expired')),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _acceptingCode = null);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.message),
          action: SnackBarAction(label: 'Retry', onPressed: () => _accept(job)),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final profileAsync = ref.watch(driverProfileProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('VOLT Driver')),
      body: SafeArea(
        child: profileAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => Center(
            child: Text(
              error is ApiException ? error.message : 'Something went wrong.',
              style: const TextStyle(color: AppColors.textSecondary),
            ),
          ),
          data: (profile) => profile == null
              ? const SizedBox.shrink() // main.dart routes away before this can render
              : _HomeBody(profile: profile, acceptingCode: _acceptingCode, onToggleOnline: _toggleOnline, onAccept: _accept),
        ),
      ),
    );
  }
}

class _HomeBody extends ConsumerWidget {
  const _HomeBody({
    required this.profile,
    required this.acceptingCode,
    required this.onToggleOnline,
    required this.onAccept,
  });

  final DriverProfile profile;
  final String? acceptingCode;
  final ValueChanged<bool> onToggleOnline;
  final void Function(Job job) onAccept;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final activeJobAsync = ref.watch(activeJobWatcherProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(profile.name, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                    const SizedBox(height: 2),
                    Text(
                      '${profile.vehicleNumber} · ${profile.vehicleTypeCode}',
                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 13),
                    ),
                  ],
                ),
              ),
              Switch(value: profile.isOnline, onChanged: onToggleOnline),
            ],
          ),
        ),
        const Divider(height: 24),
        Expanded(
          child: !profile.isOnline
              ? const _OfflineMessage()
              : activeJobAsync.when(
                  loading: () => const Center(child: CircularProgressIndicator()),
                  error: (error, _) => Center(
                    child: Text(
                      error is ApiException ? error.message : 'Something went wrong.',
                      style: const TextStyle(color: AppColors.textSecondary),
                    ),
                  ),
                  // isActive, not a null check: the watcher keeps publishing
                  // a job after it turns cancelled or delivered so the active
                  // job screen can explain what happened. A terminal job is
                  // not "in progress", so the board comes back here.
                  data: (activeJob) => activeJob != null && activeJob.status.isActive
                      ? _ActiveJobBanner(job: activeJob)
                      : _JobBoard(acceptingCode: acceptingCode, onAccept: onAccept),
                ),
        ),
      ],
    );
  }
}

class _OfflineMessage extends StatelessWidget {
  const _OfflineMessage();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              "You're offline. Go online to see jobs.",
              style: TextStyle(color: AppColors.textSecondary),
              textAlign: TextAlign.center,
            ),
            // Absent unless built with --dart-define=CRASH_TEST=true.
            CrashTestButton(),
          ],
        ),
      ),
    );
  }
}

/// The server enforces one active booking per driver — showing a board
/// whose every Accept would 409 is worse than not showing it. This banner
/// replaces the board entirely while a job is in progress.
class _ActiveJobBanner extends StatelessWidget {
  const _ActiveJobBanner({required this.job});

  final Job job;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.local_shipping_outlined, size: 40, color: AppColors.navy),
            const SizedBox(height: 12),
            Text('Job ${job.publicCode} in progress', style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ActiveJobScreen()),
              ),
              child: const Text('View job'),
            ),
          ],
        ),
      ),
    );
  }
}

class _JobBoard extends ConsumerWidget {
  const _JobBoard({required this.acceptingCode, required this.onAccept});

  final String? acceptingCode;
  final void Function(Job job) onAccept;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final jobsAsync = ref.watch(jobBoardWatcherProvider);

    return RefreshIndicator(
      // Pull-to-refresh stays even though the board polls itself: a driver
      // waiting on work will pull anyway, and it must do something.
      onRefresh: () =>
          ref.read(jobBoardWatcherProvider.notifier).refreshNow(),
      child: jobsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => _ErrorState(
          message: error is ApiException ? error.message : 'Something went wrong.',
          onRetry: () => ref.invalidate(jobBoardWatcherProvider),
        ),
        data: (jobs) => jobs.isEmpty
            ? _EmptyState(onRefresh: () => ref.invalidate(jobBoardWatcherProvider))
            : ListView.separated(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(24),
                itemCount: jobs.length,
                separatorBuilder: (_, _) => const SizedBox(height: 12),
                itemBuilder: (context, i) {
                  final job = jobs[i];
                  final busy = acceptingCode != null;
                  return _JobCard(
                    job: job,
                    accepting: acceptingCode == job.publicCode,
                    onAccept: busy ? null : () => onAccept(job),
                  );
                },
              ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.onRefresh});

  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('No jobs right now', style: TextStyle(color: AppColors.textSecondary)),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: onRefresh, child: const Text('Refresh')),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, style: const TextStyle(color: AppColors.textSecondary), textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

class _JobCard extends StatelessWidget {
  const _JobCard({required this.job, required this.accepting, required this.onAccept});

  final Job job;
  final bool accepting;
  final VoidCallback? onAccept;

  String _agoText(DateTime createdAt) {
    final minutes = DateTime.now().toUtc().difference(createdAt.toUtc()).inMinutes;
    if (minutes < 1) return 'just now';
    if (minutes < 60) return '$minutes min ago';
    return '${(minutes / 60).floor()}h ago';
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
        color: Colors.white,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${job.pickupAddress} → ${job.dropAddress}',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
              Text(
                '₹${job.quotedFareInr.round()}',
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18, color: AppColors.navy),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '${job.goodsDescription} · ${job.approxWeightKg}kg',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 13),
          ),
          const SizedBox(height: 2),
          Text(
            '${(job.quotedDistanceM / 1000).toStringAsFixed(1)} km · ${job.quotedEtaMinutes} min · ${_agoText(job.createdAt)}',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 13),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: onAccept,
              child: accepting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                    )
                  : const Text('Accept'),
            ),
          ),
        ],
      ),
    );
  }
}
