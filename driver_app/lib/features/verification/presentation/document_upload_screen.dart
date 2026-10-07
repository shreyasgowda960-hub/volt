import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:volt_core/volt_core.dart';

import '../../driver/application/driver_providers.dart';
import '../data/document_picker.dart';
import '../domain/driver_document.dart';

/// Where a driver lands after registering, and where a rejected driver lands
/// again. Two slots — licence and RC — and the account moves to `submitted`
/// only once the server holds both.
class DocumentUploadScreen extends ConsumerWidget {
  const DocumentUploadScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final documentsAsync = ref.watch(driverDocumentsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Verify your account'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(sessionProvider.notifier).signOut(),
          ),
        ],
      ),
      body: SafeArea(
        child: documentsAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (error, _) => _ErrorBody(
            message: error is ApiException
                ? error.message
                : 'Could not load your documents.',
            onRetry: () => ref.invalidate(driverDocumentsProvider),
          ),
          data: (verification) => _UploadBody(verification: verification),
        ),
      ),
    );
  }
}

class _ErrorBody extends StatelessWidget {
  const _ErrorBody({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.lg),
            FilledButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

class _UploadBody extends StatelessWidget {
  const _UploadBody({required this.verification});

  final DriverVerification verification;

  @override
  Widget build(BuildContext context) {
    final wasRejected = verification.hasRejection;

    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.xl,
        vertical: AppSpacing.lg,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            wasRejected ? 'We need another look' : 'Two documents to go',
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            wasRejected
                ? 'Something was wrong with what you sent. The details are '
                    'below — replace whatever was rejected and we will review '
                    'it again.'
                : 'We check every driver before their first job. Upload your '
                    'driving licence and your vehicle RC, and we will review '
                    'them.',
            style: const TextStyle(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.xl),
          for (final type in DocumentType.values) ...[
            _DocumentSlot(type: type, document: verification.forType(type)),
            const SizedBox(height: AppSpacing.lg),
          ],
          const SizedBox(height: AppSpacing.sm),
          const Text(
            'Your documents are used only to verify you, and are deleted when '
            'your account is closed.',
            style: TextStyle(color: AppColors.textSecondary, fontSize: 12),
          ),
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }
}

/// One slot. Owns its own picked-but-not-yet-uploaded state, so picking a
/// licence never disturbs an RC upload already in flight.
class _DocumentSlot extends ConsumerStatefulWidget {
  const _DocumentSlot({required this.type, required this.document});

  final DocumentType type;

  /// The server's record for this type, if any. Null means nothing uploaded.
  final DriverDocument? document;

  @override
  ConsumerState<_DocumentSlot> createState() => _DocumentSlotState();
}

class _DocumentSlotState extends ConsumerState<_DocumentSlot> {
  final _numberController = TextEditingController();
  PickedDocument? _picked;
  bool _uploading = false;
  String? _error;

  @override
  void dispose() {
    _numberController.dispose();
    super.dispose();
  }

  /// True when the server already holds something for this type that is not
  /// rejected. The upload endpoint 409s on a second one, so the slot closes
  /// rather than offering a button that cannot work.
  bool get _isLocked {
    final status = widget.document?.status;
    return status == DocumentStatus.submitted ||
        status == DocumentStatus.approved;
  }

  Future<void> _pick(ImageSource source) async {
    try {
      final picked = await ref.read(documentPickerProvider).pick(source);
      if (picked == null || !mounted) return;
      setState(() {
        _picked = picked;
        _error = null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Could not open that. Try the other option.');
    }
  }

  Future<void> _upload() async {
    final picked = _picked;
    if (picked == null || _uploading) return;

    setState(() {
      _uploading = true;
      _error = null;
    });

    try {
      // ref.read inside a handler, NOT a provider. An upload is a mutation and
      // there is no idempotency key — a watched provider's auto-retry would
      // post the image twice, and the second would 409 against the first.
      await ref.read(driverRepositoryProvider).uploadDocument(
            type: widget.type,
            bytes: picked.bytes,
            filename: picked.filename,
            documentNumber: _numberController.text.trim(),
          );

      if (!mounted) return;
      setState(() => _picked = null);

      // Both providers, and both for a reason: the documents list redraws this
      // slot as submitted, and the profile is what routing watches — once the
      // server holds both documents it flips to `submitted` and the gate moves
      // this driver on to PendingReviewScreen.
      ref.invalidate(driverDocumentsProvider);
      ref.invalidate(driverProfileProvider);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'Upload failed. Try again.');
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  void _chooseSource() {
    showModalBottomSheet<void>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const Text('Take a photo'),
              onTap: () {
                Navigator.pop(sheetContext);
                _pick(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Choose from gallery'),
              onTap: () {
                Navigator.pop(sheetContext);
                _pick(ImageSource.gallery);
              },
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final document = widget.document;

    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  widget.type.label,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: AppColors.navy,
                  ),
                ),
              ),
              if (document != null) _StatusChip(status: document.status),
            ],
          ),
          if (document != null &&
              document.status == DocumentStatus.rejected &&
              document.rejectionReason != null) ...[
            const SizedBox(height: AppSpacing.md),
            _RejectionNotice(reason: document.rejectionReason!),
          ],
          const SizedBox(height: AppSpacing.md),
          if (_isLocked)
            Text(
              document!.status == DocumentStatus.approved
                  ? 'Approved. Nothing more to do here.'
                  : 'Sent for review. We will let you know.',
              style: const TextStyle(
                color: AppColors.textSecondary,
                fontSize: 13,
              ),
            )
          else ...[
            if (_picked != null) ...[
              // Shown BEFORE upload so a driver can see they photographed the
              // right document, rather than finding out from a rejection.
              ClipRRect(
                borderRadius: BorderRadius.circular(AppRadius.md),
                child: Image.memory(
                  Uint8List.fromList(_picked!.bytes),
                  height: 160,
                  width: double.infinity,
                  fit: BoxFit.cover,
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              TextField(
                controller: _numberController,
                maxLength: 64,
                textCapitalization: TextCapitalization.characters,
                decoration: InputDecoration(
                  labelText: '${widget.type.label} number (optional)',
                  helperText: 'Helps us match the photo to the record.',
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  Expanded(
                    child: FilledButton(
                      onPressed: _uploading ? null : _upload,
                      child: _uploading
                          ? const SizedBox(
                              height: 22,
                              width: 22,
                              child: CircularProgressIndicator(
                                strokeWidth: 2.5,
                                color: AppColors.onPrimary,
                              ),
                            )
                          : const Text('Upload'),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.md),
                  TextButton(
                    onPressed: _uploading ? null : _chooseSource,
                    child: const Text('Replace'),
                  ),
                ],
              ),
            ] else
              OutlinedButton.icon(
                onPressed: _chooseSource,
                icon: const Icon(Icons.add_a_photo_outlined),
                label: Text(
                  document?.status == DocumentStatus.rejected
                      ? 'Upload a new photo'
                      : 'Add a photo',
                ),
              ),
          ],
          if (_error != null) ...[
            const SizedBox(height: AppSpacing.md),
            Text(
              _error!,
              style: const TextStyle(color: AppColors.error, fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status});

  final DocumentStatus status;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      DocumentStatus.submitted => ('Under review', AppColors.textSecondary),
      DocumentStatus.approved => ('Approved', AppColors.success),
      // warning, not primary: amber is for actions, and a rejection is not one.
      DocumentStatus.rejected => ('Rejected', AppColors.warning),
    };

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

/// The reviewer's reason, against the document it belongs to. Never a summary
/// at the top of the screen — a driver with one bad photo out of two has to be
/// able to see WHICH one.
class _RejectionNotice extends StatelessWidget {
  const _RejectionNotice({required this.reason});

  final String reason;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.warning.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Text(
        reason,
        style: const TextStyle(color: AppColors.textPrimary, fontSize: 13),
      ),
    );
  }
}
