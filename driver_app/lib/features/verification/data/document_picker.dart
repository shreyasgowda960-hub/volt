import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

/// An image chosen by the driver, already read into memory and ready to post.
class PickedDocument {
  const PickedDocument({required this.bytes, required this.filename});

  final List<int> bytes;
  final String filename;
}

/// Wraps image_picker so no widget talks to a platform plugin directly.
///
/// IMAGES ONLY, by choice. The backend also accepts PDF, but a driver
/// photographs a licence — they do not have one as a file. Supporting PDF from
/// the app would mean a second dependency (a document picker) for a path
/// nobody on a phone takes.
class DocumentPicker {
  DocumentPicker({ImagePicker? picker}) : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  /// Returns null when the driver backs out of the camera or gallery.
  ///
  /// The downscale is deliberately MILD. A reviewer has to read a licence
  /// number off this image, so the limit is upload time on mobile data, not
  /// the server's 10MB cap — a raw phone JPEG is 2-8MB and would clear the cap
  /// untouched. Degrading it to the point of illegibility would just produce a
  /// rejection and a second upload.
  Future<PickedDocument?> pick(ImageSource source) async {
    final file = await _picker.pickImage(
      source: source,
      maxWidth: 2000,
      imageQuality: 85,
    );
    if (file == null) return null;

    final bytes = await file.readAsBytes();
    // Cosmetic: the server sniffs the leading bytes and ignores both the
    // filename and the declared content type, because both are caller-supplied.
    return PickedDocument(bytes: bytes, filename: file.name);
  }
}

final documentPickerProvider = Provider<DocumentPicker>((ref) {
  return DocumentPicker();
});
