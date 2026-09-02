import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../../driver/application/driver_providers.dart';
import '../domain/job.dart';

/// No driver_id or customer phone number in BookingResponse today — see the
/// spec 010 report. Rather than invent a contact-info row, this screen
/// simply doesn't show one; a driver with no way to reach the customer is a
/// real product gap, not something to paper over here.
class ActiveJobScreen extends ConsumerStatefulWidget {
  const ActiveJobScreen({super.key, required this.job});

  final Job job;

  @override
  ConsumerState<ActiveJobScreen> createState() => _ActiveJobScreenState();
}

class _ActiveJobScreenState extends ConsumerState<ActiveJobScreen> {
  late Job _job;
  bool _working = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _job = widget.job;
  }

  Future<bool> _confirm(String title) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Confirm')),
        ],
      ),
    );
    return result ?? false;
  }

  Future<void> _markPickedUp() async {
    if (!await _confirm('Confirm pickup?')) return;
    setState(() {
      _working = true;
      _error = null;
    });
    try {
      final updated = await ref.read(driverRepositoryProvider).markPickedUp(_job.publicCode);
      if (!mounted) return;
      setState(() => _job = updated);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _markDelivered() async {
    if (!await _confirm('Confirm delivery?')) return;
    setState(() {
      _working = true;
      _error = null;
    });
    try {
      await ref.read(driverRepositoryProvider).markDelivered(_job.publicCode);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Delivered')),
      );
      Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_job.publicCode)),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '₹${_job.quotedFareInr.round()}',
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 28, color: AppColors.navy),
              ),
              const SizedBox(height: 20),
              _InfoRow(icon: Icons.trip_origin, label: 'Pickup', value: _job.pickupAddress),
              const SizedBox(height: 12),
              _InfoRow(icon: Icons.location_on_outlined, label: 'Drop', value: _job.dropAddress),
              const SizedBox(height: 12),
              _InfoRow(icon: Icons.inventory_2_outlined, label: 'Goods', value: _job.goodsDescription),
              const SizedBox(height: 12),
              _InfoRow(icon: Icons.scale_outlined, label: 'Weight', value: '${_job.approxWeightKg}kg'),
              if (_error != null) ...[
                const SizedBox(height: 16),
                Text(_error!, style: const TextStyle(color: AppColors.danger, fontSize: 13)),
              ],
              const Spacer(),
              if (_job.status == JobStatus.driverAssigned)
                FilledButton(
                  onPressed: _working ? null : _markPickedUp,
                  child: _working ? _spinner() : const Text('Picked up'),
                )
              else if (_job.status == JobStatus.pickedUp)
                FilledButton(
                  onPressed: _working ? null : _markDelivered,
                  child: _working ? _spinner() : const Text('Delivered'),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _spinner() => const SizedBox(
        height: 22,
        width: 22,
        child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
      );
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.icon, required this.label, required this.value});

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, color: AppColors.navy, size: 20),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
              Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
            ],
          ),
        ),
      ],
    );
  }
}
