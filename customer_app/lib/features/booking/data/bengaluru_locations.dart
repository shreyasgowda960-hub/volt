import '../domain/location.dart';

/// Hardcoded stand-in for Google Places Autocomplete. Real lat/lng so the
/// haversine-based fare estimate looks credible in the demo.
const bengaluruLocations = [
  Location(name: 'Koramangala', lat: 12.9352, lng: 77.6245),
  Location(name: 'Indiranagar', lat: 12.9784, lng: 77.6408),
  Location(name: 'Whitefield', lat: 12.9698, lng: 77.7500),
  Location(name: 'Electronic City', lat: 12.8452, lng: 77.6602),
  Location(name: 'Hebbal', lat: 13.0358, lng: 77.5970),
  Location(name: 'Jayanagar', lat: 12.9250, lng: 77.5938),
];
