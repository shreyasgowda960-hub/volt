import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../../driver/application/driver_providers.dart';
import '../domain/job.dart';

const _interval = Duration(seconds: 5);

/// Polls the job board so new work appears without the driver touching
/// anything.
///
/// There is no stop condition in here, and that is deliberate. "Stop when the
/// driver goes offline" and "stop when they already hold a job" are both
/// already true of the *widget*: the board is only built in that state. When
/// it is not, nothing watches this provider, autoDispose tears the notifier
/// down, and the poller dies with it. Re-checking those conditions here would
/// duplicate the rule in a second place that could disagree with the first.
class JobBoardWatcher extends AsyncNotifier<List<Job>> {
  Poller? _poller;
  bool _disposed = false;

  @override
  Future<List<Job>> build() async {
    ref.onDispose(() {
      _disposed = true;
      _poller?.dispose();
      _poller = null;
    });

    final jobs = await _fetch();
    _poller = Poller(interval: _interval, onTick: _poll)..start();
    return jobs;
  }

  Future<List<Job>> _fetch() =>
      ref.read(driverRepositoryProvider).availableJobs();

  Future<void> _poll() async {
    try {
      final jobs = await _fetch();
      if (_disposed) return;
      state = AsyncData(jobs);
    } catch (_) {
      // An empty board and an unreachable server look identical if a failed
      // poll is allowed to write. Keep the last list and say nothing — the
      // pull-to-refresh and Retry paths surface errors when the driver asks.
      if (_disposed) return;
    }
  }

  Future<void> refreshNow() => _poll();
}

/// autoDispose is what stops this polling forever — AsyncNotifierProvider is
/// keep-alive by default in Riverpod 3.
final jobBoardWatcherProvider =
    AsyncNotifierProvider.autoDispose<JobBoardWatcher, List<Job>>(
        JobBoardWatcher.new);

/// Polls the one job this driver currently holds.
///
/// The case this exists for: the customer cancels while the driver is already
/// en route. A driver arriving at a pickup that no longer exists is the worst
/// outcome the system can produce, and without polling they would only find
/// out by tapping something.
///
/// It follows one specific booking rather than re-running "find my active
/// job" each tick. Once cancelled, that booking stops matching an active
/// filter, so a filter-based poll would just see null and could not tell
/// "cancelled under me" from "nothing assigned" — the difference the driver
/// most needs to hear about.
class ActiveJobWatcher extends AsyncNotifier<Job?> {
  Poller? _poller;
  bool _disposed = false;
  String? _watchedCode;

  @override
  Future<Job?> build() async {
    ref.onDispose(() {
      _disposed = true;
      _poller?.dispose();
      _poller = null;
    });

    final job = await _findActive();

    // No active job means no polling at all. A job can only *become* active
    // through this driver's own Accept, and that path invalidates this
    // provider, so there is nothing a timer here could discover.
    if (job != null) {
      _watchedCode = job.publicCode;
      _poller = Poller(interval: _interval, onTick: _poll)..start();
    }

    return job;
  }

  Future<Job?> _findActive() async {
    final jobs = await ref.read(driverRepositoryProvider).myJobs();
    for (final job in jobs) {
      if (job.status.isActive) return job;
    }
    return null;
  }

  Future<void> _poll() async {
    final code = _watchedCode;
    if (code == null) return;

    try {
      final jobs = await ref.read(driverRepositoryProvider).myJobs();
      if (_disposed) return;

      final watched = jobs.where((j) => j.publicCode == code).firstOrNull;

      if (watched == null) {
        // Gone entirely — nothing left to report about it.
        state = const AsyncData(null);
        _poller?.stopForever();
        return;
      }

      // Published even when terminal, so the active-job screen can see
      // *which* terminal state it reached and say so. It is the home screen's
      // job to stop showing the in-progress banner for a non-active status.
      state = AsyncData(watched);
      if (!watched.status.isActive) _poller?.stopForever();
    } catch (_) {
      // Same reasoning as the board: a failed poll must not make it look like
      // the job disappeared. That would send a driver back to the board
      // mid-delivery over one dropped request.
      if (_disposed) return;
    }
  }

  Future<void> refreshNow() => _poll();

  /// Replaces the tracked job after a local action (pickup, deliver) so the
  /// screen updates immediately instead of waiting up to 5s for the next
  /// tick. Terminal statuses also stop the poller, since nothing follows.
  void applyLocalUpdate(Job job) {
    if (_disposed) return;
    _watchedCode = job.publicCode;
    state = AsyncData(job);
    if (!job.status.isActive) _poller?.stopForever();
  }
}

final activeJobWatcherProvider =
    AsyncNotifierProvider.autoDispose<ActiveJobWatcher, Job?>(
        ActiveJobWatcher.new);
