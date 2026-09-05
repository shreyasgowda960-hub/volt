import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../application/booking_providers.dart';
import '../domain/place.dart';
import 'address_picker_screen.dart';
import 'vehicle_select_screen.dart';

class BookingHomeScreen extends ConsumerStatefulWidget {
  const BookingHomeScreen({super.key});

  @override
  ConsumerState<BookingHomeScreen> createState() => _BookingHomeScreenState();
}

class _BookingHomeScreenState extends ConsumerState<BookingHomeScreen> {
  final _goodsController = TextEditingController();
  final _weightController = TextEditingController();

  @override
  void dispose() {
    _goodsController.dispose();
    _weightController.dispose();
    super.dispose();
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
        // The phone number lives here rather than as a loose grey line at the
        // top of the body. It is orientation, not content — it belongs with
        // the identity of the screen, not in the flow of it.
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'VOLT',
              style: TextStyle(
                fontWeight: FontWeight.w800,
                fontSize: 20,
                letterSpacing: 0.5,
              ),
            ),
            Text(
              session?.phone ?? 'Signed in',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w500,
                color: Colors.white.withValues(alpha: 0.7),
              ),
            ),
          ],
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
                    Text(
                      'Where to?',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    const Text(
                      'Search an address or drop a pin to see fares.',
                      style: TextStyle(
                        color: AppColors.textSecondary,
                        fontSize: 14,
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xl),

                    // Pickup and drop as ONE object, not two. They describe a
                    // single journey, and the connector between them is what
                    // makes that legible at a glance.
                    _SectionCard(
                      padding: EdgeInsets.zero,
                      child: Column(
                        children: [
                          _RouteRow(
                            label: 'PICKUP',
                            hint: 'Search pickup address',
                            place: pickup,
                            isOrigin: true,
                            onTap: () => _pick(isPickup: true),
                          ),
                          const _RouteConnector(),
                          _RouteRow(
                            label: 'DROP',
                            hint: 'Search drop address',
                            place: drop,
                            isOrigin: false,
                            onTap: () => _pick(isPickup: false),
                          ),
                        ],
                      ),
                    ),

                    if (sameLocation) ...[
                      const SizedBox(height: AppSpacing.md),
                      const _InlineError(
                        "Pickup and drop can't be the same",
                      ),
                    ],

                    const SizedBox(height: AppSpacing.xl),
                    const _SectionLabel('CONSIGNMENT'),
                    const SizedBox(height: AppSpacing.md),
                    _SectionCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const _FieldLabel('What are you sending?'),
                          const SizedBox(height: AppSpacing.sm),
                          TextField(
                            controller: _goodsController,
                            maxLength: 255,
                            textCapitalization: TextCapitalization.sentences,
                            decoration: const InputDecoration(
                              hintText: 'e.g. Two cartons of books',
                              prefixIcon: Icon(Icons.inventory_2_outlined),
                              // The 0/255 counter is noise: 255 is a database
                              // limit, not a target anyone is writing towards.
                              counterText: '',
                            ),
                            onChanged: (_) => setState(() {}),
                          ),
                          const SizedBox(height: AppSpacing.lg),
                          const _FieldLabel('Approximate weight'),
                          const SizedBox(height: AppSpacing.sm),
                          TextField(
                            controller: _weightController,
                            keyboardType: const TextInputType.numberWithOptions(
                              decimal: true,
                            ),
                            decoration: const InputDecoration(
                              hintText: 'e.g. 12.5',
                              prefixIcon: Icon(Icons.scale_outlined),
                              // Unit as a suffix rather than "(kg)" bolted on
                              // to the label — it belongs next to the number.
                              suffixText: 'kg',
                              suffixStyle: TextStyle(
                                color: AppColors.textSecondary,
                                fontWeight: FontWeight.w600,
                              ),
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
                onPressed: canProceed
                    ? () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => VehicleSelectScreen(
                              goodsDescription: goodsDescription,
                              approxWeightKg: approxWeightKg,
                            ),
                          ),
                        )
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

/// A white panel with a hairline border. Elevation is a shadow rather than a
/// Material surface tint, which on a near-white background reads as dirt.
class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.child,
    this.padding = const EdgeInsets.all(AppSpacing.lg),
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
        boxShadow: [
          BoxShadow(
            color: AppColors.navy.withValues(alpha: 0.04),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: child,
    );
  }
}

/// Small caps section heading. Sits outside its card so the card stays a
/// single uninterrupted surface.
class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 11,
        fontWeight: FontWeight.w700,
        letterSpacing: 1.2,
        color: AppColors.textSecondary,
      ),
    );
  }
}

class _FieldLabel extends StatelessWidget {
  const _FieldLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: const TextStyle(
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: AppColors.textPrimary,
      ),
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
    required this.hint,
    required this.place,
    required this.isOrigin,
    required this.onTap,
  });

  final String label;
  final String hint;
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
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.lg,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 28,
              child: Center(
                child: isOrigin ? const _OriginDot() : const _DestinationPin(),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.1,
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  if (chosen == null)
                    Text(
                      hint,
                      style: const TextStyle(
                        color: AppColors.textDisabled,
                        fontSize: 15,
                      ),
                    )
                  else ...[
                    Text(
                      chosen.shortAddress,
                      style: const TextStyle(
                        fontWeight: FontWeight.w600,
                        fontSize: 15,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      chosen.address,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.textSecondary,
                        fontSize: 12,
                        height: 1.35,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.md),
              child: Icon(
                chosen == null ? Icons.search : Icons.edit_outlined,
                size: 18,
                color: chosen == null ? AppColors.textDisabled : AppColors.navy,
              ),
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
      height: 14,
      width: 14,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: AppColors.navy, width: 3),
      ),
    );
  }
}

/// Destination marker: solid amber, so the two ends of the journey are
/// distinguishable without reading the labels.
class _DestinationPin extends StatelessWidget {
  const _DestinationPin();

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 14,
      width: 14,
      decoration: BoxDecoration(
        color: AppColors.primary,
        shape: BoxShape.circle,
        border: Border.all(color: AppColors.navy, width: 2),
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
          width: AppSpacing.lg + 28,
          child: Column(
            children: List.generate(
              3,
              (_) => Container(
                height: 3,
                width: 3,
                margin: const EdgeInsets.symmetric(vertical: 1.5),
                decoration: const BoxDecoration(
                  color: AppColors.textDisabled,
                  shape: BoxShape.circle,
                ),
              ),
            ),
          ),
        ),
        const Expanded(child: Divider(height: 1)),
        const SizedBox(width: AppSpacing.lg),
      ],
    );
  }
}

class _InlineError extends StatelessWidget {
  const _InlineError(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm + 2,
      ),
      decoration: BoxDecoration(
        color: AppColors.error.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, size: 16, color: AppColors.error),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(color: AppColors.error, fontSize: 13),
            ),
          ),
        ],
      ),
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
