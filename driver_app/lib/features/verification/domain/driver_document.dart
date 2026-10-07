/// Mirrors the backend's DocumentType. Two values, and AADHAAR IS DELIBERATELY
/// ABSENT — see app/models/driver_document.py and docs/future-plans.md before
/// adding a third.
enum DocumentType {
  drivingLicence('driving_licence', 'Driving licence'),
  vehicleRc('vehicle_rc', 'Vehicle RC');

  const DocumentType(this.wireValue, this.label);

  final String wireValue;
  final String label;

  static DocumentType fromWire(String value) {
    return DocumentType.values.firstWhere((t) => t.wireValue == value);
  }
}

/// Per-document review state. There is no `pending`: a row exists only once
/// something was uploaded, so `submitted` is the first state a document can
/// be in. Driver-level pending (nothing uploaded) lives on
/// [DriverVerification.status] instead.
enum DocumentStatus {
  submitted,
  approved,
  rejected;

  static DocumentStatus fromWire(String value) {
    return DocumentStatus.values.firstWhere((s) => s.name == value);
  }
}

/// One uploaded document as the DRIVER sees it.
///
/// Note what is not here: no signed URL and no storage path. The backend's
/// driver-facing response carries neither by design, and a field added here
/// would be the first pressure to add one there.
class DriverDocument {
  const DriverDocument({
    required this.id,
    required this.type,
    required this.status,
    this.documentNumber,
    this.rejectionReason,
    this.uploadedAt,
    this.reviewedAt,
  });

  final int id;
  final DocumentType type;
  final DocumentStatus status;
  final String? documentNumber;
  final String? rejectionReason;
  final DateTime? uploadedAt;
  final DateTime? reviewedAt;

  factory DriverDocument.fromJson(Map<String, dynamic> json) {
    return DriverDocument(
      id: json['id'] as int,
      type: DocumentType.fromWire(json['document_type'] as String),
      status: DocumentStatus.fromWire(json['status'] as String),
      documentNumber: json['document_number'] as String?,
      rejectionReason: json['rejection_reason'] as String?,
      uploadedAt: _parseDate(json['uploaded_at']),
      reviewedAt: _parseDate(json['reviewed_at']),
    );
  }

  static DateTime? _parseDate(Object? value) {
    if (value is! String) return null;
    return DateTime.tryParse(value)?.toLocal();
  }
}

/// The driver's own verification state in one object — what
/// GET /api/v1/drivers/me/documents returns.
///
/// [status] rides along with the documents because it is what routing depends
/// on, and asking /drivers/me for it separately would be a round trip for a
/// field already in hand.
class DriverVerification {
  const DriverVerification({required this.status, required this.documents});

  final VerificationStatus status;
  final List<DriverDocument> documents;

  /// The document that represents this type's CURRENT state.
  ///
  /// After a resubmission there are TWO rows of the same type: the rejected
  /// original, which stays on the record forever in case the rejection is ever
  /// disputed, and the new one under review. The live one wins, or a driver
  /// who has already re-uploaded would keep being shown a stale rejection and
  /// a button to fix something they fixed.
  ///
  /// Decided here from id, not from the order the server sent — the endpoint
  /// happens to return newest-first today, and silently depending on that
  /// would make a reordering upstream look like an app bug.
  DriverDocument? forType(DocumentType type) {
    DriverDocument? best;
    for (final doc in documents) {
      if (doc.type != type) continue;
      if (best == null) {
        best = doc;
        continue;
      }
      final bestIsLive = best.status != DocumentStatus.rejected;
      final docIsLive = doc.status != DocumentStatus.rejected;
      if (bestIsLive != docIsLive) {
        if (docIsLive) best = doc;
      } else if (doc.id > best.id) {
        best = doc;
      }
    }
    return best;
  }

  /// True when anything the driver is looking at was rejected. Drives the
  /// wording at the top of the upload screen.
  ///
  /// NOT `status == rejected`: if both documents were rejected and the driver
  /// has re-uploaded one of them, the driver-level status is back to `pending`
  /// while a rejection is still on screen against the other slot.
  bool get hasRejection => DocumentType.values
      .map(forType)
      .any((d) => d?.status == DocumentStatus.rejected);

  factory DriverVerification.fromJson(Map<String, dynamic> json) {
    final docs = (json['documents'] as List<dynamic>? ?? <dynamic>[])
        .map((d) => DriverDocument.fromJson(d as Map<String, dynamic>))
        .toList();
    return DriverVerification(
      status: VerificationStatus.fromWire(
        json['verification_status'] as String?,
      ),
      documents: docs,
    );
  }
}

/// Where a driver is in document review. Unlike the booking lifecycle this
/// one LOOPS — rejected goes back to submitted on resubmission.
enum VerificationStatus {
  pending,
  submitted,
  approved,
  rejected;

  /// An unrecognised value falls back to [pending] rather than throwing.
  ///
  /// A status this build has never heard of means the server is ahead of the
  /// app. Routing such a driver to the upload screen is wrong but recoverable;
  /// throwing would put them on the error screen with no way forward, and
  /// `approved` would be worse still — it would route an unverified driver
  /// into the job board, where every call 403s.
  static VerificationStatus fromWire(String? value) {
    for (final status in VerificationStatus.values) {
      if (status.name == value) return status;
    }
    return VerificationStatus.pending;
  }
}
