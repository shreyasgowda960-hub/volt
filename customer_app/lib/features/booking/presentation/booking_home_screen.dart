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
        title: const Text('VOLT', style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(sessionProvider.notifier).signOut(),
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 16),
              Text(
                'Signed in as ${session?.phone ?? "unknown"}',
                style: const TextStyle(color: AppColors.textSecondary, fontSize: 13),
              ),
              const SizedBox(height: 20),
              const Text(
                'Where to?',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              const Text(
                'Search an address or drop a pin to see fares.',
                style: TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: 24),
              const Text(
                'Pickup',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: 8),
              _AddressRow(
                icon: Icons.trip_origin,
                hint: 'Search pickup address',
                place: pickup,
                onTap: () => _pick(isPickup: true),
              ),
              const SizedBox(height: 20),
              const Text(
                'Drop',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: 8),
              _AddressRow(
                icon: Icons.location_on_outlined,
                hint: 'Search drop address',
                place: drop,
                onTap: () => _pick(isPickup: false),
              ),
              if (sameLocation) ...[
                const SizedBox(height: 12),
                const Text(
                  "Pickup and drop can't be the same",
                  style: TextStyle(color: AppColors.danger, fontSize: 13),
                ),
              ],
              const SizedBox(height: 20),
              const Text(
                'What are you sending?',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _goodsController,
                maxLength: 255,
                decoration: const InputDecoration(
                  hintText: 'e.g. Two cartons of books',
                  prefixIcon: Icon(Icons.inventory_2_outlined),
                ),
                onChanged: (_) => setState(() {}),
              ),
              const Text(
                'Approx. weight (kg)',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _weightController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(
                  hintText: 'e.g. 12.5',
                  prefixIcon: Icon(Icons.scale_outlined),
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: 24),
              FilledButton(
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
              const SizedBox(height: 24),
              // Absent unless built with --dart-define=CRASH_TEST=true.
              const CrashTestButton(),
            ],
          ),
        ),
      ),
    );
  }
}

/// A tappable address row, replacing the dropdown of six hardcoded areas.
///
/// Shows the full address once chosen rather than a short label: the
/// difference between two addresses on the same street is in the part a
/// truncated label would cut off.
class _AddressRow extends StatelessWidget {
  const _AddressRow({
    required this.icon,
    required this.hint,
    required this.place,
    required this.onTap,
  });

  final IconData icon;
  final String hint;
  final Place? place;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final chosen = place;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: chosen == null ? AppColors.border : AppColors.navy,
          ),
        ),
        child: Row(
          children: [
            Icon(icon, size: 20, color: AppColors.navy),
            const SizedBox(width: 12),
            Expanded(
              child: chosen == null
                  ? Text(
                      hint,
                      style: const TextStyle(color: AppColors.textSecondary),
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          chosen.shortAddress,
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          chosen.address,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: AppColors.textSecondary,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
            ),
            const SizedBox(width: 8),
            Text(
              chosen == null ? '' : 'Change',
              style: const TextStyle(
                color: AppColors.navy,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
