import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../application/booking_providers.dart';
import '../data/bengaluru_locations.dart';
import '../domain/location.dart';
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
            ],
          ),
        ),
      ),
    );
  }
}
