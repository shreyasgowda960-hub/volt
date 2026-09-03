import 'dart:math';

import 'package:volt_core/volt_core.dart';

import '../domain/place.dart';

/// Thrown when reverse geocoding finds no address at a point — a pin in a
/// lake, or unmapped land. A real answer the customer can act on by moving
/// the pin, not a failure to apologise for, so it is not an [ApiException].
class NoAddressAtPoint implements Exception {
  const NoAddressAtPoint();
}

/// Address lookup.
///
/// Every call goes to OUR backend, never to Google directly. An API key with
/// an Android application restriction does not work against the Places or
/// Geocoding web services — verified: Google answers REQUEST_DENIED, "not
/// authorized... with empty referer" — so a client-side implementation would
/// need an unrestricted key sitting extractable inside the APK, billable to
/// us by anyone who pulled it out. The key stays on the server.
abstract interface class PlacesService {
  /// Autocomplete suggestions for [query], biased to the service area.
  ///
  /// [sessionToken] must be the same value for every call in one search and
  /// must also be passed to [detail] for the place the user picks. See
  /// [newSessionToken].
  Future<List<PlaceSuggestion>> suggest(String query, String sessionToken);

  /// Coordinates and full address for a chosen suggestion.
  ///
  /// Pass the search's [sessionToken] — this call is what closes the billing
  /// session that [suggest] opened.
  Future<Place> detail(String placeId, String sessionToken);

  /// Address for a dropped pin. Throws [NoAddressAtPoint] if there is none.
  Future<Place> reverseGeocode(double lat, double lng);

  /// Where VOLT operates. Fetched once and cached for the session.
  Future<ServiceArea> serviceArea();
}

/// Generates a session token for one search.
///
/// This looks like pointless plumbing and is the single most expensive thing
/// in this feature to get wrong. Places Autocomplete bills per request, so
/// typing a 20-character address is 20 charges — unless every request in that
/// search carries the same session token AND the final Place Details call
/// carries it too. Then Google bundles the whole thing into one billable
/// session.
///
/// The rules, all three of which matter:
///   - one token per search, generated when the user starts typing;
///   - the same token on every suggest call and on the final detail call;
///   - never reused for a second search — a reused token is treated as no
///     token at all, and every request is billed separately again.
///
/// A v4 UUID is what Google recommends. Built from Random.secure here rather
/// than adding a uuid package for sixteen bytes.
String newSessionToken() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  // Version 4, variant 1, per RFC 4122.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  String hex(int start, int end) => bytes
      .sublist(start, end)
      .map((b) => b.toRadixString(16).padLeft(2, '0'))
      .join();

  return '${hex(0, 4)}-${hex(4, 6)}-${hex(6, 8)}-${hex(8, 10)}-${hex(10, 16)}';
}

class RemotePlacesService implements PlacesService {
  RemotePlacesService(this._api);

  final ApiClient _api;

  @override
  Future<List<PlaceSuggestion>> suggest(
    String query,
    String sessionToken,
  ) async {
    // POST, not GET, because the search text is usually somebody's home or
    // workplace and a GET would put it in the request line, which the
    // server's access log records and retains.
    final json = await _api.post('/api/v1/places/autocomplete', {
      'query': query,
      'session_token': sessionToken,
    });
    final raw = json['suggestions'] as List<dynamic>? ?? <dynamic>[];
    return raw
        .map((s) => PlaceSuggestion.fromJson(s as Map<String, dynamic>))
        .toList();
  }

  @override
  Future<Place> detail(String placeId, String sessionToken) async {
    final json = await _api.post('/api/v1/places/details', {
      'place_id': placeId,
      'session_token': sessionToken,
    });
    return _placeFrom(json);
  }

  @override
  Future<Place> reverseGeocode(double lat, double lng) async {
    try {
      final json = await _api.post('/api/v1/places/reverse-geocode', {
        'lat': lat,
        'lng': lng,
      });
      return _placeFrom(json);
    } on ApiException catch (e) {
      // 404 here means Google succeeded and there is simply no address at
      // that point — distinct from the server or the network failing.
      if (e.statusCode == 404) throw const NoAddressAtPoint();
      rethrow;
    }
  }

  @override
  Future<ServiceArea> serviceArea() async {
    final json = await _api.get('/api/v1/service-area');
    return ServiceArea.fromJson(json);
  }

  Place _placeFrom(Map<String, dynamic> json) {
    final placeId = json['place_id'] as String?;
    return Place(
      address: json['address'] as String? ?? '',
      lat: (json['lat'] as num).toDouble(),
      lng: (json['lng'] as num).toDouble(),
      placeId: (placeId == null || placeId.isEmpty) ? null : placeId,
    );
  }
}
