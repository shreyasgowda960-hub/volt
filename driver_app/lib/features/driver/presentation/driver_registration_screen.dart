import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import '../application/driver_providers.dart';
import '../domain/vehicle_type_option.dart';

class DriverRegistrationScreen extends ConsumerStatefulWidget {
  const DriverRegistrationScreen({super.key});

  @override
  ConsumerState<DriverRegistrationScreen> createState() =>
      _DriverRegistrationScreenState();
}

class _DriverRegistrationScreenState
    extends ConsumerState<DriverRegistrationScreen> {
  final _nameController = TextEditingController();
  final _vehicleNumberController = TextEditingController();
  VehicleTypeOption? _selectedType;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _nameController.dispose();
    _vehicleNumberController.dispose();
    super.dispose();
  }

  bool get _canSubmit =>
      !_submitting &&
      _nameController.text.trim().isNotEmpty &&
      _vehicleNumberController.text.trim().isNotEmpty &&
      _selectedType != null;

  Future<void> _submit() async {
    if (!_canSubmit) return;

    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      // Indian plate formats vary enough that strict regex validation
      // causes false rejections — non-empty and a length cap is the check.
      await ref.read(driverRepositoryProvider).register(
            name: _nameController.text.trim(),
            vehicleNumber: _vehicleNumberController.text.trim().toUpperCase(),
            vehicleTypeCode: _selectedType!.code,
          );
      // Routing on driverProfileProvider moves on once this resolves.
      ref.invalidate(driverProfileProvider);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Something went wrong. Try again.');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final vehicleTypesAsync = ref.watch(vehicleTypesProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Driver registration')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "You're almost there",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              const Text(
                'Tell us about you and your vehicle to start accepting jobs.',
                style: TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: 24),
              const Text(
                'Full name',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _nameController,
                maxLength: 100,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(hintText: 'e.g. Ravi Kumar'),
                onChanged: (_) => setState(() {}),
              ),
              const Text(
                'Vehicle number',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _vehicleNumberController,
                maxLength: 20,
                textCapitalization: TextCapitalization.characters,
                inputFormatters: [UpperCaseTextFormatter()],
                decoration: const InputDecoration(hintText: 'e.g. KA 05 AB 1234'),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: 12),
              const Text(
                'Vehicle type',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: 8),
              vehicleTypesAsync.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(vertical: 16),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (error, _) => Text(
                  error is ApiException ? error.message : 'Could not load vehicle types.',
                  style: const TextStyle(color: AppColors.danger),
                ),
                data: (types) => DropdownButtonFormField<VehicleTypeOption>(
                  isExpanded: true,
                  initialValue: _selectedType,
                  hint: const Text('Select vehicle type'),
                  items: types
                      .map(
                        (t) => DropdownMenuItem(
                          value: t,
                          child: Text('${t.label} (up to ${t.capacityKg}kg)'),
                        ),
                      )
                      .toList(),
                  onChanged: (t) => setState(() => _selectedType = t),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(
                  _error!,
                  style: const TextStyle(color: AppColors.danger, fontSize: 13),
                ),
              ],
              const SizedBox(height: 28),
              FilledButton(
                onPressed: _canSubmit ? _submit : null,
                child: _submitting
                    ? const SizedBox(
                        height: 22,
                        width: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Register'),
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}

class UpperCaseTextFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    return newValue.copyWith(text: newValue.text.toUpperCase());
  }
}
