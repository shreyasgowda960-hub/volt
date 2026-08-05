import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../auth/application/auth_providers.dart';
import '../application/booking_providers.dart';
import '../data/bengaluru_locations.dart';
import '../domain/location.dart';
import 'vehicle_select_screen.dart';

class BookingHomeScreen extends ConsumerWidget {
  const BookingHomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    final pickup = ref.watch(pickupLocationProvider);
    final drop = ref.watch(dropLocationProvider);

    final sameLocation = pickup != null && drop != null && pickup == drop;
    final canProceed = pickup != null && drop != null && !sameLocation;

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
        child: Padding(
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
                'Pick a pickup and drop point to see fares.',
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
              DropdownButtonFormField<Location>(
                isExpanded: true,
                initialValue: pickup,
                hint: const Text('Select pickup location'),
                items: bengaluruLocations
                    .map((l) => DropdownMenuItem(value: l, child: Text(l.name)))
                    .toList(),
                onChanged: (l) =>
                    ref.read(pickupLocationProvider.notifier).select(l),
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.trip_origin),
                ),
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
              DropdownButtonFormField<Location>(
                isExpanded: true,
                initialValue: drop,
                hint: const Text('Select drop location'),
                items: bengaluruLocations
                    .map((l) => DropdownMenuItem(value: l, child: Text(l.name)))
                    .toList(),
                onChanged: (l) =>
                    ref.read(dropLocationProvider.notifier).select(l),
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.location_on_outlined),
                ),
              ),
              if (sameLocation) ...[
                const SizedBox(height: 12),
                const Text(
                  "Pickup and drop can't be the same",
                  style: TextStyle(color: AppColors.danger, fontSize: 13),
                ),
              ],
              const Spacer(),
              FilledButton(
                onPressed: canProceed
                    ? () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => const VehicleSelectScreen(),
                          ),
                        )
                    : null,
                child: const Text('See fare estimates'),
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}
