/// A resolved, bookable location.
///
/// Replaces the old `Location` (name + lat + lng), which existed only to
/// carry one of six hardcoded Bengaluru areas. The differences that matter:
/// the address is now free text from Google rather than a label we chose, and
/// [placeId] may be null because a dropped pin has no place id until Google
/// gives it one.
class Place {
  const Place({
    required this.address,
    required this.lat,
    required this.lng,
    this.placeId,
  });

  /// What the customer sees and what gets stored on the booking.
  final String address;

  final double lat;
  final double lng;

  /// Google's stable id, when this came from address search. Null for a pin
  /// drop that Google could not attach to a known place. Sent to the server
  /// so it can be stored — a place id is re-resolvable where free text is
  /// not, and it cannot be back-filled later.
  final String? placeId;

  /// A shorter form for a one-line row. Google's formatted addresses run
  /// long ("123, 4th Cross, ..., Bengaluru, Karnataka 560034, India") and the
  /// tail is the same for every address in the city.
  String get shortAddress {
    final firstPart = address.split(',').first.trim();
    return firstPart.isEmpty ? address : firstPart;
  }

  @override
  bool operator ==(Object other) =>
      other is Place &&
      other.lat == lat &&
      other.lng == lng &&
      other.address == address;

  @override
  int get hashCode => Object.hash(address, lat, lng);
}

/// One autocomplete suggestion. Not yet a [Place] — it has no coordinates
/// until Place Details is called for it.
class PlaceSuggestion {
  const PlaceSuggestion({
    required this.placeId,
    required this.description,
    required this.mainText,
    required this.secondaryText,
  });

  factory PlaceSuggestion.fromJson(Map<String, dynamic> json) {
    return PlaceSuggestion(
      placeId: json['place_id'] as String,
      description: json['description'] as String? ?? '',
      mainText: json['main_text'] as String? ?? '',
      secondaryText: json['secondary_text'] as String? ?? '',
    );
  }

  final String placeId;
  final String description;
  final String mainText;
  final String secondaryText;

  /// Falls back to the full description when Google returns no structured
  /// split, which happens for some establishment results.
  String get title => mainText.isNotEmpty ? mainText : description;
}

/// The area VOLT will actually serve, from GET /api/v1/service-area.
class ServiceArea {
  const ServiceArea({
    required this.centerLat,
    required this.centerLng,
    required this.radiusKm,
  });

  factory ServiceArea.fromJson(Map<String, dynamic> json) {
    return ServiceArea(
      centerLat: (json['center_lat'] as num).toDouble(),
      centerLng: (json['center_lng'] as num).toDouble(),
      radiusKm: (json['radius_km'] as num).toDouble(),
    );
  }

  final double centerLat;
  final double centerLng;
  final double radiusKm;
}
