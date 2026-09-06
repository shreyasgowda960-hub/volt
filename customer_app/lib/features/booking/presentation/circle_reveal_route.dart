import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:volt_core/volt_core.dart';

/// Pushes a page from behind a disc of [colour] that grows out of [origin].
///
/// The point is continuity: the fare screen appears to come out of the button
/// that asked for it, rather than sliding in from the side as though it were
/// unrelated. [origin] is in global coordinates — normally the centre of the
/// button that was tapped.
///
/// Two overlapping phases rather than one. The disc grows first and the page
/// fades in slightly before it finishes, so the amber is a wipe rather than a
/// wall the customer waits behind. Both are clipped to the disc, otherwise the
/// incoming page appears in the corners before the disc reaches them.
class CircleRevealRoute<T> extends PageRouteBuilder<T> {
  CircleRevealRoute({
    required WidgetBuilder builder,
    required this.origin,
    this.colour = AppColors.primary,
  }) : super(
          transitionDuration: const Duration(milliseconds: 520),
          // Coming back is faster. A reverse wipe is re-showing something the
          // customer has already seen, and matching the forward duration
          // makes Back feel sticky.
          reverseTransitionDuration: const Duration(milliseconds: 300),
          pageBuilder: (context, _, _) => builder(context),
        );

  final Offset origin;
  final Color colour;

  /// Far enough to cover the screen from wherever the disc starts — the
  /// distance to the furthest corner, not half the diagonal, because the
  /// origin is rarely the centre.
  static double _radiusToCover(Offset from, Size size) {
    final dx = math.max(from.dx, size.width - from.dx);
    final dy = math.max(from.dy, size.height - from.dy);
    return math.sqrt(dx * dx + dy * dy);
  }

  @override
  Widget buildTransitions(
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) {
    // "Remove animations" is an accessibility setting, not a preference to
    // talk anyone out of — motion sickness and vestibular disorders are real.
    // Fall back to a plain fade, which still reads as a transition.
    if (MediaQuery.of(context).disableAnimations) {
      return FadeTransition(opacity: animation, child: child);
    }

    final maxRadius = _radiusToCover(origin, MediaQuery.sizeOf(context));

    final grow = CurvedAnimation(
      parent: animation,
      curve: const Interval(0, 0.65, curve: Curves.easeOutCubic),
    );
    final fade = CurvedAnimation(
      parent: animation,
      curve: const Interval(0.40, 1, curve: Curves.easeOut),
    );

    return AnimatedBuilder(
      animation: grow,
      // Passed as `child` so the incoming page is not rebuilt every frame —
      // FadeTransition animates itself without help from this builder.
      child: Stack(
        fit: StackFit.expand,
        children: [
          ColoredBox(color: colour),
          FadeTransition(opacity: fade, child: child),
        ],
      ),
      builder: (context, staticChild) => ClipPath(
        clipper: _DiscClipper(origin, maxRadius * grow.value),
        child: staticChild,
      ),
    );
  }
}

class _DiscClipper extends CustomClipper<Path> {
  const _DiscClipper(this.centre, this.radius);

  final Offset centre;
  final double radius;

  @override
  Path getClip(Size size) =>
      Path()..addOval(Rect.fromCircle(center: centre, radius: radius));

  @override
  bool shouldReclip(_DiscClipper oldClipper) =>
      oldClipper.radius != radius || oldClipper.centre != centre;
}

/// The global centre of the widget behind [key], for use as a reveal origin.
///
/// Returns null if the widget is gone or unlaid-out, which the caller should
/// treat as "animate from the middle of the screen" rather than as an error —
/// a transition is not worth crashing a booking over.
Offset? globalCentreOf(GlobalKey key) {
  final box = key.currentContext?.findRenderObject() as RenderBox?;
  if (box == null || !box.hasSize) return null;
  return box.localToGlobal(box.size.center(Offset.zero));
}
