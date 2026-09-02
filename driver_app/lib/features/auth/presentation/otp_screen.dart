import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:volt_core/volt_core.dart';

class OtpScreen extends ConsumerStatefulWidget {
  const OtpScreen({
    super.key,
    required this.phone,
    required this.verificationId,
  });

  final String phone;
  final String verificationId;

  @override
  ConsumerState<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends ConsumerState<OtpScreen> {
  final _controller = TextEditingController();
  bool _verifying = false;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _verify() async {
    final code = _controller.text.trim();
    if (code.length != 6) {
      setState(() => _error = 'Enter the 6-digit code');
      return;
    }

    setState(() {
      _verifying = true;
      _error = null;
    });

    try {
      final session = await ref.read(authRepositoryProvider).verifyOtp(
            verificationId: widget.verificationId,
            phone: widget.phone,
            code: code,
          );
      if (!mounted) return;
      ref.read(sessionProvider.notifier).signIn(session);

      // Root widget swaps to the home/registration screen; clear the auth
      // stack above it.
      Navigator.of(context).popUntil((route) => route.isFirst);
    } on InvalidOtpException {
      if (!mounted) return;
      setState(() => _error = 'That code is incorrect');
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Something went wrong. Try again.');
    } finally {
      if (mounted) setState(() => _verifying = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 16),
              const Text(
                'Verify your number',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              Text(
                'Code sent to ${widget.phone}',
                style: const TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: 28),
              TextField(
                controller: _controller,
                autofocus: true,
                keyboardType: TextInputType.number,
                maxLength: 6,
                textAlign: TextAlign.center,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                onSubmitted: (_) => _verify(),
                style: const TextStyle(
                  fontSize: 26,
                  letterSpacing: 12,
                  fontWeight: FontWeight.w600,
                ),
                decoration: const InputDecoration(counterText: ''),
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
                onPressed: _verifying ? null : _verify,
                child: _verifying
                    ? const SizedBox(
                        height: 22,
                        width: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Verify'),
              ),
              const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}
