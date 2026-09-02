import 'dart:async';

import 'package:flutter/widgets.dart';

/// Drives a repeating async callback, and — more to the point — knows when to
/// stop driving it.
///
/// A timer that starts is trivial. This class exists for the four things that
/// are not:
///
/// 1. **Never two requests at once.** On a cold-started free-tier backend a
///    single GET can take 50s, ten times the tick interval. Without a guard
///    the ticks pile up: ten in-flight requests, ten responses landing in
///    arbitrary order, and a screen that flickers between whichever arrives
///    last. A tick that arrives while one is in flight is *dropped*, not
///    queued — queueing only defers the pile-up.
///
///    It also buys a property worth naming: since at most one request is ever
///    outstanding, responses cannot arrive out of order, so nothing here needs
///    a sequence number to discard stale ones.
///
/// 2. **Stopping permanently vs pausing.** [stopForever] is for "this will
///    never change again" — a delivered booking. Backgrounding is a pause. The
///    two must not be conflated, or coming back to the foreground restarts
///    polling on something already finished.
///
/// 3. **Never stacking timers.** Arming is idempotent ([_arm] returns early if
///    a timer is already live), so a double resume cannot produce two timers
///    ticking against each other.
///
/// 4. **Outliving its owner.** An in-flight request cannot be cancelled; it
///    will land whether or not the screen still exists. After [dispose] the
///    callback is never invoked again, so a response arriving 45s after the
///    user left has nothing to write into.
class Poller {
  Poller({required this.interval, required this.onTick, this.onError});

  final Duration interval;
  final Future<void> Function() onTick;

  /// Notified if [onTick] throws. Optional, because a well-behaved callback
  /// handles its own failures — but see [_tick] for why Poller cannot simply
  /// let the error escape.
  final void Function(Object error, StackTrace stackTrace)? onError;

  Timer? _timer;
  AppLifecycleListener? _lifecycle;

  bool _inFlight = false;
  bool _stopped = false;
  bool _disposed = false;

  /// True once [stopForever] has been called. Callers use this to avoid
  /// re-arming something that is finished.
  bool get isStopped => _stopped;

  /// Whether a tick timer is currently armed.
  ///
  /// Exposed for tests, because "callbacks stopped" and "the timer is
  /// actually cancelled" are two different things and only the first is
  /// observable from outside. [_tick] checks `_stopped` and `_disposed`
  /// itself, so a stopped-but-uncancelled periodic timer keeps firing every
  /// interval — doing nothing, but keeping this object and its closure
  /// reachable for the life of the app. That leak is the whole reason this
  /// class exists, and without this getter no test could catch it.
  @visibleForTesting
  bool get hasArmedTimer => _timer?.isActive ?? false;

  /// Runs [onTick] immediately, then every `interval` after that, and starts
  /// watching the app lifecycle.
  ///
  /// Pass `fetchImmediately: false` when the owner has ALREADY loaded the
  /// state this poller refreshes. A Riverpod notifier fetches in `build()` to
  /// have something to return, so leaving this on made both fire for the same
  /// data — two identical GETs about 90ms apart on every screen open, and
  /// again on every invalidate. Resuming from the background still fetches
  /// immediately regardless; that one is not a duplicate.
  ///
  /// Safe to call more than once — the second call does nothing.
  void start({bool fetchImmediately = true}) {
    if (_disposed || _stopped) return;

    _lifecycle ??= AppLifecycleListener(
      // onPause/onResume deliberately, not onInactive/onHide. `inactive`
      // fires for transient interruptions — the notification shade, a
      // permission dialog — and treating those as "backgrounded" would
      // cancel and re-arm the timer constantly while the app is plainly
      // still on screen.
      onPause: _pause,
      onResume: _resumeAndFetch,
    );

    _arm();
    // Fire-and-forget on purpose: start() is called from build() and must not
    // wait 50s for a cold start before the timer exists.
    if (fetchImmediately) unawaited(_tick());
  }

  /// Stops polling for good. Idempotent, and not undone by a later [start] or
  /// by the app returning to the foreground.
  void stopForever() {
    _stopped = true;
    _timer?.cancel();
    _timer = null;
  }

  /// Cancels everything and guarantees `onTick` is never called again.
  ///
  /// Must be called from the owner's disposal path — for a Riverpod notifier,
  /// `ref.onDispose`. The [AppLifecycleListener] is a binding observer and
  /// leaks if it is not disposed.
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    _timer = null;
    _lifecycle?.dispose();
    _lifecycle = null;
  }

  void _arm() {
    if (_disposed || _stopped) return;
    // Idempotent: an already-live timer is left alone rather than replaced,
    // so no path can end up with two.
    if (_timer != null && _timer!.isActive) return;
    _timer = Timer.periodic(interval, (_) => unawaited(_tick()));
  }

  void _pause() {
    // Cancel the timer but leave _stopped alone — this is a pause, and the
    // difference is what stops a resume from reviving a finished poll.
    _timer?.cancel();
    _timer = null;
  }

  void _resumeAndFetch() {
    if (_disposed || _stopped) return;
    _arm();
    // Immediately, not on the next tick: the user is looking at the screen
    // right now, and up to `interval` of staleness after a two-minute
    // background is exactly what they would notice.
    unawaited(_tick());
  }

  Future<void> _tick() async {
    if (_inFlight || _stopped || _disposed) return;

    _inFlight = true;
    try {
      await onTick();
    } catch (error, stackTrace) {
      // Caught rather than rethrown, and that is not defensiveness. Every
      // call site here is `unawaited(_tick())` — a timer callback has no
      // caller to return an error to — so a throw that escaped would become
      // an unhandled zone error every single interval. Once a poll starts
      // failing that is one uncatchable exception every 5 seconds for as
      // long as the screen is open.
      onError?.call(error, stackTrace);
    } finally {
      // Also load-bearing. If _inFlight were left true, every future tick
      // would return early and polling would die silently — no error, no
      // spinner, just a screen that quietly stops updating.
      _inFlight = false;
    }
  }
}
