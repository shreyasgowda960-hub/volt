import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../domain/booking.dart';
import 'booking_providers.dart';

/// What the status screen renders: the booking, plus how badly out of date it
/// might be.
///
/// The failure count is part of the state rather than a private field because
/// the screen has to be able to say "not updating". Keeping it private would
/// mean the only way to surface a failing poll is to overwrite the booking
/// with an error — which is exactly what must not happen.
class BookingWatchState {
  const BookingWatchState({
    required this.booking,
    this.consecutiveFailures = 0,
  });

  final Booking booking;
  final int consecutiveFailures;

  /// Three misses is about fifteen seconds of silence — long enough to be a
  /// real problem, short enough that the customer has not yet decided the app
  /// is broken.
  bool get isStale => consecutiveFailures >= 3;

  BookingWatchState copyWith({Booking? booking, int? consecutiveFailures}) {
    return BookingWatchState(
      booking: booking ?? this.booking,
      consecutiveFailures: consecutiveFailures ?? this.consecutiveFailures,
    );
  }
}

/// Polls one booking for as long as its status can still change.
///
/// The mechanics — the 5s timer, the in-flight guard, pausing on background,
/// surviving disposal — all live in [Poller]. What is here is the part that is
/// specific to a booking: when to stop for good, and what a failed poll should
/// do to the screen.
///
/// **Failures are handled in two different ways on purpose.** If the *first*
/// load fails there is nothing worth preserving, so it becomes a real
/// AsyncError and Riverpod's automatic retry takes over — safe here precisely
/// because this is a GET. If a *later* poll fails, the booking already on
/// screen is still the best information anyone has, so the error is swallowed
/// and only the failure counter moves. A customer mid-delivery must never
/// watch their booking vanish because one request timed out on a train.
///
/// That is the opposite of how create-booking and accept are treated: those
/// are mutations, must never sit in a provider, and must never be auto-retried.
class BookingWatcher extends AsyncNotifier<BookingWatchState> {
  BookingWatcher(this.publicCode);

  final String publicCode;

  static const _interval = Duration(seconds: 5);

  Poller? _poller;
  bool _disposed = false;

  @override
  Future<BookingWatchState> build() async {
    ref.onDispose(() {
      // Ordering matters: mark disposed first, so a response already in
      // flight cannot write into a dead notifier between these two lines.
      _disposed = true;
      _poller?.dispose();
      _poller = null;
    });

    final booking = await _fetch();

    // Only now, with a status in hand, is it possible to know whether polling
    // is wanted at all. Opening the screen on an already-delivered booking
    // should start no timer whatsoever — arming first and stopping on the
    // first tick means one pointless request and 5s of spinner on something
    // that finished yesterday.
    if (!booking.status.isTerminal) {
      // fetchImmediately: false — build() just fetched, above.
      _poller = Poller(interval: _interval, onTick: _poll)
        ..start(fetchImmediately: false);
    }

    return BookingWatchState(booking: booking);
  }

  Future<Booking> _fetch() =>
      ref.read(bookingRepositoryProvider).byPublicCode(publicCode);

  /// One poll. Never throws — see the class doc for why a late failure must
  /// not disturb what is on screen.
  Future<void> _poll() async {
    try {
      final booking = await _fetch();
      if (_disposed) return;

      state = AsyncData(BookingWatchState(booking: booking));

      if (booking.status.isTerminal) {
        // Permanent. Not a pause: coming back from the background must not
        // revive polling on a finished booking, and Poller.stopForever is
        // what guarantees that.
        _poller?.stopForever();
      }
    } catch (_) {
      if (_disposed) return;
      // Deliberately does not touch the booking. Only the counter moves, so
      // the screen keeps showing the last good state with a quiet hint.
      // `value` is the nullable accessor in Riverpod 3 (valueOrNull is gone).
      // Null here means the first load has not landed yet, and that case is
      // already an AsyncError with retry — nothing to preserve.
      final current = state.value;
      if (current != null) {
        state = AsyncData(
          current.copyWith(
            consecutiveFailures: current.consecutiveFailures + 1,
          ),
        );
      }
    }
  }

  /// Manual refresh. Kept because polling fails, and when it does this is the
  /// only thing the customer can actually do.
  Future<void> refreshNow() => _poll();
}

/// autoDispose is load-bearing, not tidiness.
///
/// AsyncNotifierProvider is keep-alive by DEFAULT in Riverpod 3
/// (`isAutoDispose = false` in the family builder). Declared the obvious way,
/// this notifier would outlive the screen that watches it and keep polling a
/// finished booking until the app is killed — a poll that never stops. The
/// dispose hook in [BookingWatcher.build] only ever runs because of this.
final bookingWatcherProvider = AsyncNotifierProvider.autoDispose
    .family<BookingWatcher, BookingWatchState, String>(BookingWatcher.new);
