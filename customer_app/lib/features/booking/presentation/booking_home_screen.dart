import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../application/booking_providers.dart';
import '../domain/place.dart';
import 'address_picker_screen.dart';
import 'circle_reveal_route.dart';
import 'vehicle_select_screen.dart';

class BookingHomeScreen extends ConsumerStatefulWidget {
  const BookingHomeScreen({super.key});

  @override
  ConsumerState<BookingHomeScreen> createState() => _BookingHomeScreenState();
}

class _BookingHomeScreenState extends ConsumerState<BookingHomeScreen> {
  final _goodsController = TextEditingController();
  final _weightController = TextEditingController();

  /// Submitting the goods field jumps here rather than dismissing the
  /// keyboard, so the two fields are one continuous action.
  final _weightFocus = FocusNode();

  /// The reveal starts from this button, so the fare screen appears to come
  /// out of the thing that asked for it.
  final _ctaKey = GlobalKey();

  @override
  void dispose() {
    _goodsController.dispose();
    _weightController.dispose();
    _weightFocus.dispose();
    super.dispose();
  }

  /// What to call the customer.
  ///
  /// The phone number today. THIS IS THE ONE LINE TO CHANGE when profiles
  /// land and a real name is available — everything else about the greeting
  /// stays as it is.
  String _greeting(VoltSession? session) {
    final phone = session?.phone;
    if (phone == null || phone.isEmpty) return 'there';
    return phone;
  }

  Future<void> _pick({required bool isPickup}) async {
    // Hand the current selection in so the picker reopens where the customer
    // left off — map mode centres on it, and the pin starts there rather
    // than at the city centre.
    final current = isPickup
        ? ref.read(pickupLocationProvider)
        : ref.read(dropLocationProvider);

    final chosen = await Navigator.of(context).push<Place>(
      MaterialPageRoute(
        builder: (_) => AddressPickerScreen(
          title: isPickup ? 'Pickup location' : 'Drop location',
          initial: current,
        ),
      ),
    );
    if (chosen == null || !mounted) return;
    if (isPickup) {
      ref.read(pickupLocationProvider.notifier).select(chosen);
    } else {
      ref.read(dropLocationProvider.notifier).select(chosen);
    }
  }

  void _seeFares(String goodsDescription, double approxWeightKg) {
    // Dismiss the keyboard first: a reveal playing behind a keyboard that is
    // also animating out looks like two unrelated things happening at once.
    FocusScope.of(context).unfocus();

    Navigator.of(context).push(
      CircleRevealRoute<void>(
        origin: globalCentreOf(_ctaKey) ??
            (Offset.zero & MediaQuery.sizeOf(context)).center,
        builder: (_) => VehicleSelectScreen(
          goodsDescription: goodsDescription,
          approxWeightKg: approxWeightKg,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final pickup = ref.watch(pickupLocationProvider);
    final drop = ref.watch(dropLocationProvider);

    final sameLocation = pickup != null && drop != null && pickup == drop;
    final goodsDescription = _goodsController.text.trim();
    final approxWeightKg = double.tryParse(_weightController.text.trim());
    final canProceed = pickup != null &&
        drop != null &&
        !sameLocation &&
        goodsDescription.isNotEmpty &&
        approxWeightKg != null &&
        approxWeightKg > 0;

    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'VOLT',
          style: TextStyle(
            fontWeight: FontWeight.w800,
            fontSize: 20,
            letterSpacing: 0.5,
          ),
        ),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(sessionProvider.notifier).signOut(),
          ),
          const SizedBox(width: AppSpacing.xs),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.xl,
                  AppSpacing.xl,
                  AppSpacing.xl,
                  AppSpacing.xl,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // The only heading on the screen. The old "Where to?" said
                    // nothing the fields below it do not already say.
                    Text.rich(
                      TextSpan(
                        children: [
                          const TextSpan(
                            text: 'Hi, ',
                            style: TextStyle(
                              fontWeight: FontWeight.w400,
                              color: AppColors.textSecondary,
                            ),
                          ),
                          TextSpan(text: _greeting(session)),
                        ],
                      ),
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xl),

                    // Pickup and drop as ONE object, not two. They describe a
                    // single journey, and the connector between them is what
                    // makes that legible at a glance.
                    _Panel(
                      padding: EdgeInsets.zero,
                      child: Column(
                        children: [
                          _RouteRow(
                            label: 'Pickup',
                            place: pickup,
                            isOrigin: true,
                            onTap: () => _pick(isPickup: true),
                          ),
                          const _RouteConnector(),
                          _RouteRow(
                            label: 'Drop',
                            place: drop,
                            isOrigin: false,
                            onTap: () => _pick(isPickup: false),
                          ),
                        ],
                      ),
                    ),

                    if (sameLocation) ...[
                      const SizedBox(height: AppSpacing.md),
                      const _InlineError("Pickup and drop can't be the same"),
                    ],

                    const SizedBox(height: AppSpacing.md),

                    // No section heading and no labels above the fields: the
                    // floating labels carry the copy, which is one row of
                    // text saved on a screen that had too many.
                    _Panel(
                      child: Column(
                        children: [
                          TextField(
                            controller: _goodsController,
                            maxLength: 255,
                            textCapitalization: TextCapitalization.sentences,
                            textInputAction: TextInputAction.next,
                            onSubmitted: (_) => _weightFocus.requestFocus(),
                            style: const TextStyle(fontSize: 15),
                            decoration: _denseField(
                              label: 'What are you sending?',
                              hint: 'e.g. Two cartons of books',
                              icon: Icons.inventory_2_outlined,
                            ),
                            onChanged: (_) => setState(() {}),
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          TextField(
                            controller: _weightController,
                            focusNode: _weightFocus,
                            keyboardType: const TextInputType.numberWithOptions(
                              decimal: true,
                            ),
                            textInputAction: TextInputAction.done,
                            style: const TextStyle(fontSize: 15),
                            decoration: _denseField(
                              label: 'Approx. weight',
                              hint: 'e.g. 12.5',
                              icon: Icons.scale_outlined,
                              suffix: 'kg',
                            ),
                            onChanged: (_) => setState(() {}),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    // Absent unless built with --dart-define=CRASH_TEST=true.
                    const CrashTestButton(),
                  ],
                ),
              ),
            ),

            // Pinned rather than scrolled away. The whole screen exists to
            // reach this button, and on a small phone with the keyboard up it
            // was previously below the fold.
            _BottomBar(
              child: FilledButton(
                key: _ctaKey,
                onPressed: canProceed
                    ? () => _seeFares(goodsDescription, approxWeightKg)
                    : null,
                child: const Text('See fare estimates'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Compact field styling: floating label instead of a heading above the box,
/// and the counter hidden — 255 is a database limit, not a target anyone is
/// writing towards.
InputDecoration _denseField({
  required String label,
  required String hint,
  required IconData icon,
  String? suffix,
}) {
  return InputDecoration(
    labelText: label,
    hintText: hint,
    counterText: '',
    isDense: true,
    filled: false,
    prefixIcon: Icon(icon, size: 20),
    suffixText: suffix,
    suffixStyle: const TextStyle(
      color: AppColors.textSecondary,
      fontWeight: FontWeight.w600,
    ),
    contentPadding: const EdgeInsets.symmetric(vertical: 14),
    border: InputBorder.none,
    enabledBorder: InputBorder.none,
    focusedBorder: InputBorder.none,
    errorBorder: InputBorder.none,
    focusedErrorBorder: InputBorder.none,
  );
}

/// A white panel with a hairline border. No shadow: at this density the
/// screen is a stack of quiet surfaces, and shadows on all of them read as
/// clutter rather than as depth.
class _Panel extends StatelessWidget {
  const _Panel({
    required this.child,
    this.padding = const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
  });

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.border),
      ),
      child: child,
    );
  }
}

/// One leg of the journey.
///
/// Shows the full address once chosen rather than a short label: the
/// difference between two addresses on the same street is in the part a
/// truncated label would cut off.
class _RouteRow extends StatelessWidget {
  const _RouteRow({
    required this.label,
    required this.place,
    required this.isOrigin,
    required this.onTap,
  });

  final String label;
  final Place? place;
  final bool isOrigin;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final chosen = place;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.vertical(
        top: Radius.circular(isOrigin ? AppRadius.lg : 0),
        bottom: Radius.circular(isOrigin ? 0 : AppRadius.lg),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md + 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            SizedBox(
              width: 22,
              child: Center(
                child: isOrigin ? const _OriginDot() : const _DestinationDot(),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: chosen == null
                  ? Text(
                      label,
                      style: const TextStyle(
                        color: AppColors.textDisabled,
                        fontSize: 15,
                      ),
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          chosen.shortAddress,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontWeight: FontWeight.w600,
                            fontSize: 15,
                            color: AppColors.textPrimary,
                          ),
                        ),
                        Text(
                          chosen.address,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.textSecondary,
                            fontSize: 12,
                            height: 1.3,
                          ),
                        ),
                      ],
                    ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Icon(
              chosen == null ? Icons.search : Icons.edit_outlined,
              size: 17,
              color: chosen == null ? AppColors.textDisabled : AppColors.navy,
            ),
          ],
        ),
      ),
    );
  }
}

/// Origin marker: a ring, the map convention for "start here".
class _OriginDot extends StatelessWidget {
  const _OriginDot();

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 12,
      width: 12,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: AppColors.navy, width: 2.5),
      ),
    );
  }
}

/// Destination marker: solid amber, so the two ends of the journey are
/// distinguishable without reading the labels.
class _DestinationDot extends StatelessWidget {
  const _DestinationDot();

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 12,
      width: 12,
      decoration: BoxDecoration(
        color: AppColors.primary,
        shape: BoxShape.circle,
        border: Border.all(color: AppColors.navy, width: 1.5),
      ),
    );
  }
}

/// The dotted run between origin and destination, aligned under the markers.
class _RouteConnector extends StatelessWidget {
  const _RouteConnector();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 22,
          child: Column(
            children: List.generate(
              3,
              (_) => Container(
                height: 2.5,
                width: 2.5,
                margin: const EdgeInsets.symmetric(vertical: 1),
                decoration: const BoxDecoration(
                  color: AppColors.textDisabled,
                  shape: BoxShape.circle,
                ),
              ),
            ),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        const Expanded(child: Divider(height: 1)),
      ],
    );
  }
}

class _InlineError extends StatelessWidget {
  const _InlineError(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Icon(Icons.error_outline, size: 15, color: AppColors.error),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(color: AppColors.error, fontSize: 13),
          ),
        ),
      ],
    );
  }
}

/// The action bar. A top hairline rather than a shadow, so it reads as the
/// edge of the scrolling area rather than as a floating object.
class _BottomBar extends StatelessWidget {
  const _BottomBar({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.xl,
        AppSpacing.md,
        AppSpacing.xl,
        AppSpacing.md,
      ),
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: child,
    );
  }
}
