import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

import 'otp_screen.dart';

class PhoneEntryScreen extends ConsumerStatefulWidget {
  const PhoneEntryScreen({super.key});

  @override
  ConsumerState<PhoneEntryScreen> createState() => _PhoneEntryScreenState();
}

class _PhoneEntryScreenState extends ConsumerState<PhoneEntryScreen> {
  final _controller = TextEditingController();
  bool _sending = false;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  String? _validate(String raw) {
    if (raw.length != 10) return 'Enter a 10-digit mobile number';
    if (!RegExp(r'^[6-9]\d{9}$').hasMatch(raw)) {
      return 'Indian mobile numbers start with 6, 7, 8 or 9';
    }
    return null;
  }

  Future<void> _submit() async {
    final raw = _controller.text.trim();
    final problem = _validate(raw);
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }

    setState(() {
      _sending = true;
      _error = null;
    });

    final phone = '+91$raw';
    try {
      final verificationId =
          await ref.read(authRepositoryProvider).requestOtp(phone);
      if (!mounted) return;
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) =>
              OtpScreen(phone: phone, verificationId: verificationId),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Could not send the code. Try again.');
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 64),
              Row(
                children: [
                  const Icon(Icons.bolt, color: AppColors.yellow, size: 40),
                  const SizedBox(width: 4),
                  Text(
                    'VOLT',
                    style: Theme.of(context).textTheme.displaySmall?.copyWith(
                          color: AppColors.navy,
                          fontWeight: FontWeight.w800,
                          letterSpacing: -1,
                        ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              const Text(
                'Quicker. Smarter. Delivered.',
                style: TextStyle(color: AppColors.textSecondary, fontSize: 15),
              ),
              const SizedBox(height: 56),
              const Text(
                'Enter your mobile number',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              const Text(
                "We'll send you a 6-digit code to verify.",
                style: TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: 20),
              TextField(
                controller: _controller,
                autofocus: true,
                keyboardType: TextInputType.phone,
                maxLength: 10,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                onSubmitted: (_) => _submit(),
                style: const TextStyle(fontSize: 18, letterSpacing: 1.2),
                decoration: const InputDecoration(
                  prefixText: '+91  ',
                  prefixStyle: TextStyle(
                    fontSize: 18,
                    color: AppColors.navy,
                    fontWeight: FontWeight.w600,
                  ),
                  hintText: '9876543210',
                  counterText: '',
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(
                  _error!,
                  style: const TextStyle(color: AppColors.danger, fontSize: 13),
                ),
              ],
              const SizedBox(height: 28),
              FilledButton(
                onPressed: _sending ? null : _submit,
                child: _sending
                    ? const SizedBox(
                        height: 22,
                        width: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Continue'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
