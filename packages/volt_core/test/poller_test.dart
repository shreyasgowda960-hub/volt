import 'package:flutter_test/flutter_test.dart';
import 'package:volt_core/volt_core.dart';

/// [Poller] is where every subtlety of spec 011's polling lifecycle lives, and
/// almost none of it is visible on device — a stacked timer or a poll that
/// never stops looks fine until you read the server log. Short real durations
/// rather than FakeAsync, because the behaviour under test is the interaction
/// between a periodic timer and an async callback that outlives its interval,
/// which is exactly what FakeAsync makes hard to reason about.
void main() {
  // AppLifecycleListener registers a binding observer, so it needs a binding.
  TestWidgetsFlutterBinding.ensureInitialized();

  const tick = Duration(milliseconds: 20);

  test('fetches immediately on start, without waiting for the first tick',
      () async {
    var calls = 0;
    final poller = Poller(interval: const Duration(hours: 1), onTick: () async {
      calls++;
    });

    poller.start();
    await Future<void>.delayed(Duration.zero);

    expect(calls, 1);
    poller.dispose();
  });

  test('keeps ticking on the interval', () async {
    var calls = 0;
    final poller = Poller(interval: tick, onTick: () async {
      calls++;
    });

    poller.start();
    await Future<void>.delayed(tick * 6);
    poller.dispose();

    // Immediate call plus several ticks. Loose bounds on purpose — this
    // asserts "it repeats", not wall-clock precision.
    expect(calls, greaterThan(2));
  });

  test('skips ticks while a request is still in flight, and does not queue',
      () async {
    var started = 0;
    // Each request takes five intervals. A stacking poller would launch a new
    // one every 20ms and rack up a dozen; this must run them strictly back to
    // back.
    final poller = Poller(interval: tick, onTick: () async {
      started++;
      await Future<void>.delayed(tick * 5);
    });

    poller.start();
    await Future<void>.delayed(tick * 11);
    poller.dispose();

    // ~11 intervals of elapsed time, ~5 intervals per request: two or three
    // requests, nowhere near the ten a stacking implementation would fire.
    expect(started, lessThanOrEqualTo(3));
    expect(started, greaterThanOrEqualTo(1));
  });

  test('a throwing tick reports the error and keeps polling', () async {
    var calls = 0;
    final errors = <Object>[];
    final poller = Poller(
      interval: tick,
      onTick: () async {
        calls++;
        throw StateError('poll failed');
      },
      onError: (error, _) => errors.add(error),
    );

    poller.start();
    await Future<void>.delayed(tick * 5);
    poller.dispose();

    // Two guarantees at once. The finally in _tick: without it the first
    // throw leaves _inFlight true forever and polling dies after one call.
    // And the catch: the error reaches onError instead of escaping into the
    // zone as an unhandled exception once per interval — which is exactly
    // how this test failed before the catch was added.
    expect(calls, greaterThan(1));
    expect(errors, isNotEmpty);
    expect(errors.first, isStateError);
  });

  test('stopForever stops, and start cannot revive it', () async {
    var calls = 0;
    final poller = Poller(interval: tick, onTick: () async {
      calls++;
    });

    poller.start();
    await Future<void>.delayed(tick * 3);
    poller.stopForever();
    final callsAtStop = calls;

    poller.start(); // must be ignored — terminal means terminal
    await Future<void>.delayed(tick * 5);

    expect(poller.isStopped, isTrue);
    expect(calls, callsAtStop);
    poller.dispose();
  });

  test('nothing is called after dispose', () async {
    var calls = 0;
    final poller = Poller(interval: tick, onTick: () async {
      calls++;
    });

    poller.start();
    await Future<void>.delayed(tick * 3);
    poller.dispose();
    final callsAtDispose = calls;

    await Future<void>.delayed(tick * 5);

    expect(calls, callsAtDispose);
  });

  test('repeated start does not stack timers', () async {
    var calls = 0;
    final poller = Poller(interval: tick, onTick: () async {
      calls++;
    });

    // Three starts. If each armed its own Timer.periodic, the tick rate would
    // roughly triple.
    poller.start();
    poller.start();
    poller.start();

    await Future<void>.delayed(tick * 10);
    poller.dispose();

    // One timer over ~10 intervals lands around 11 calls; three timers would
    // be in the thirties. 20 is a generous ceiling that still separates them.
    expect(calls, lessThan(20));
  });
}
