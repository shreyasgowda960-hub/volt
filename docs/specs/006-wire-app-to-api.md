# Spec 006 — Wire the Flutter app to the API

Build mode. After this, the server decides prices and bookings persist.

**Precondition:** spec 005 complete. Phone auth works on device, server
verifies tokens, `pytest` and `flutter analyze` both clean.

## Guardrails

- **Do NOT delete `FareEstimator` or `FakeAuthRepository`.** Both stay as
  fallbacks and for tests. The local estimator becomes display-only.
- **Do NOT add status polling or a driver-advance endpoint.** That is spec 007.
- **Do NOT hardcode the API base URL in Dart source.** It changes with every
  WiFi network.
- Only two new dependencies: `dio` and `flutter_dotenv` is NOT needed — use
  `--dart-define` instead.

## The problem this solves

Right now the app computes its own fare. Anyone can decompile the APK, patch
`perKmRate`, and book a mini-truck for ₹5. After this spec the client sends
locations and a vehicle choice, never a price, and the server's number is the
only one that matters.

---

## Step 1 — Base URL configuration

The phone cannot reach `127.0.0.1` — that is the phone's own loopback. It needs
the laptop's LAN address.

Find it:

```powershell
ipconfig | Select-String "IPv4"
```

Take the one on your WiFi adapter, e.g. `192.168.1.7`.

**New file: `customer_app/lib/core/config/app_config.dart`**

```dart
/// Injected at build time via --dart-define, so the LAN IP never lands in
/// source control and changes without editing code:
///
///   flutter run -d RMX3371 --dart-define=API_BASE_URL=http://192.168.1.7:8000
///
/// Deployed builds pass the real https URL instead.
abstract final class AppConfig {
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  static bool get isConfigured => apiBaseUrl.isNotEmpty;
}
```

`10.0.2.2` is the Android emulator's alias for the host machine. It is a
sensible default but will not work on a physical device — always pass
`--dart-define` when running on the phone.

## Step 2 — Allow cleartext HTTP in debug only

Android blocks plain HTTP by default. Your local server has no TLS.

**New file: `customer_app/android/app/src/debug/res/xml/network_security_config.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <!-- Debug builds only. Release builds keep Android's HTTPS-only default. -->
    <base-config cleartextTrafficPermitted="true" />
</network-security-config>
```

Then in `customer_app/android/app/src/debug/AndroidManifest.xml`, add the
`android:networkSecurityConfig` attribute to the `<application>` tag pointing
at `@xml/network_security_config`. Create the `<application>` tag if the debug
manifest does not have one — it merges with the main manifest.

**It must be the `debug/` source set, not `main/`.** Putting it in `main/`
would ship an APK that accepts unencrypted traffic, which is a real
man-in-the-middle risk once there are real users.

## Step 3 — Add dio

```powershell
cd $env:USERPROFILE\projects\volt\customer_app
flutter pub add dio
```

`dio` over the simpler `http` package for one reason: interceptors. Attaching
the Firebase token to every request in one place, rather than remembering it at
each call site, is worth the extra dependency.

## Step 4 — New file: `customer_app/lib/core/network/api_client.dart`

```dart
import 'package:dio/dio.dart';

import '../../features/auth/data/auth_token_provider.dart';
import '../config/app_config.dart';

/// Thrown for anything the UI should show a message for.
class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  bool get isUnauthorized => statusCode == 401;

  @override
  String toString() => 'ApiException($statusCode): $message';
}

class ApiClient {
  ApiClient({required AuthTokenProvider tokenProvider, Dio? dio})
      : _tokenProvider = tokenProvider,
        _dio = dio ?? Dio() {
    _dio.options
      ..baseUrl = AppConfig.apiBaseUrl
      ..connectTimeout = const Duration(seconds: 10)
      ..receiveTimeout = const Duration(seconds: 15)
      ..contentType = 'application/json';

    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          // Fetched per request, never cached: Firebase ID tokens expire after
          // an hour and the SDK refreshes them transparently on read.
          final token = await _tokenProvider.currentToken();
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
      ),
    );
  }

  final Dio _dio;
  final AuthTokenProvider _tokenProvider;

  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body,
  ) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(path, data: body);
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw _translate(e);
    }
  }

  Future<Map<String, dynamic>> get(String path) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>(path);
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw _translate(e);
    }
  }

  ApiException _translate(DioException e) {
    final status = e.response?.statusCode;

    if (e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.connectionError) {
      return const ApiException(
        'Cannot reach VOLT. Check your connection and try again.',
      );
    }
    if (status == 401) {
      return const ApiException('Session expired. Please sign in again.',
          statusCode: 401);
    }
    if (status == 422) {
      return const ApiException('Something in that request was invalid.',
          statusCode: 422);
    }
    if (status != null && status >= 500) {
      return ApiException('VOLT is having trouble. Try again shortly.',
          statusCode: status);
    }

    final detail = e.response?.data;
    final message = detail is Map && detail['detail'] is String
        ? detail['detail'] as String
        : 'Something went wrong.';
    return ApiException(message, statusCode: status);
  }
}
```

Note the error messages are written for a customer, not a developer. The user
never sees a status code.

## Step 5 — Make the fare estimator an interface

**Edit `customer_app/lib/features/booking/data/fare_estimator.dart`:**

Extract an interface and rename the existing class:

```dart
abstract interface class FareEstimator {
  Future<List<FareEstimate>> estimateAll(Location pickup, Location drop);
}
```

The current implementation becomes `LocalFareEstimator implements
FareEstimator`, with `estimateAll` made `async` to match. Keep the maths
exactly as it is.

Add a comment at the top of `LocalFareEstimator`:

```dart
/// DISPLAY ONLY. The server is the authority on price — see
/// RemoteFareEstimator. This exists as an offline fallback and for tests, and
/// its output must never be sent to the server or treated as a real quote.
```

## Step 6 — New file: `customer_app/lib/features/booking/data/remote_fare_estimator.dart`

```dart
import '../../../core/network/api_client.dart';
import '../domain/fare_estimate.dart';
import '../domain/location.dart';
import '../domain/vehicle_type.dart';
import 'fare_estimator.dart';

class RemoteFareEstimator implements FareEstimator {
  RemoteFareEstimator(this._api);

  final ApiClient _api;

  @override
  Future<List<FareEstimate>> estimateAll(Location pickup, Location drop) async {
    final json = await _api.post('/api/v1/bookings/estimate', {
      'pickup': {
        'address': pickup.name,
        'lat': pickup.lat,
        'lng': pickup.lng,
      },
      'drop': {
        'address': drop.name,
        'lat': drop.lat,
        'lng': drop.lng,
      },
    });

    final options = (json['options'] as List<dynamic>? ?? <dynamic>[]);
    return options.map((raw) {
      final o = raw as Map<String, dynamic>;
      return FareEstimate(
        vehicleType: _vehicleFromCode(o['vehicle_type_code'] as String),
        distanceKm: (o['distance_m'] as num) / 1000,
        fareInr: (o['fare_paise'] as num) / 100,
        etaMinutes: o['eta_minutes'] as int,
      );
    }).toList();
  }

  VehicleType _vehicleFromCode(String code) => switch (code) {
        'bike' => VehicleType.bike,
        'three_wheeler' => VehicleType.threeWheeler,
        'mini_truck' => VehicleType.miniTruck,
        _ => throw ArgumentError('Unknown vehicle type code: $code'),
      };
}
```

Note the paise-to-rupee conversion happens at the edge. The wire format is
integer paise throughout; only the display layer sees rupees.

## Step 7 — New file: `customer_app/lib/features/booking/data/booking_repository.dart`

```dart
import '../../../core/network/api_client.dart';
import '../domain/booking.dart';
import '../domain/location.dart';
import '../domain/vehicle_type.dart';

abstract interface class BookingRepository {
  Future<Booking> create({
    required Location pickup,
    required Location drop,
    required VehicleType vehicleType,
    required String goodsDescription,
    required double approxWeightKg,
  });

  Future<Booking> byPublicCode(String publicCode);
}

class RemoteBookingRepository implements BookingRepository {
  RemoteBookingRepository(this._api);

  final ApiClient _api;

  @override
  Future<Booking> create({
    required Location pickup,
    required Location drop,
    required VehicleType vehicleType,
    required String goodsDescription,
    required double approxWeightKg,
  }) async {
    final json = await _api.post('/api/v1/bookings', {
      'pickup': {'address': pickup.name, 'lat': pickup.lat, 'lng': pickup.lng},
      'drop': {'address': drop.name, 'lat': drop.lat, 'lng': drop.lng},
      'vehicle_type_code': _codeFor(vehicleType),
      'goods_description': goodsDescription,
      'approx_weight_kg': approxWeightKg,
      'payment_method': 'cash',
    });
    return Booking.fromJson(json);
  }

  @override
  Future<Booking> byPublicCode(String publicCode) async {
    final json = await _api.get('/api/v1/bookings/$publicCode');
    return Booking.fromJson(json);
  }

  String _codeFor(VehicleType v) => switch (v) {
        VehicleType.bike => 'bike',
        VehicleType.threeWheeler => 'three_wheeler',
        VehicleType.miniTruck => 'mini_truck',
      };
}
```

Note no price is sent. The server recomputes it.

## Step 8 — New file: `customer_app/lib/features/booking/domain/booking.dart`

A domain model mirroring `BookingResponse` from the API: `publicCode`,
`status` (reuse the existing `BookingStatus` enum, mapping the server's
snake_case strings), `vehicleTypeCode`, `pickupAddress`, `dropAddress`,
`goodsDescription`, `approxWeightKg`, `quotedFarePaise`, `quotedDistanceM`,
`quotedEtaMinutes`, `finalFarePaise` (nullable), `paymentMethod`, `createdAt`.

Include a `fromJson` factory. Add a `quotedFareInr` getter returning
`quotedFarePaise / 100` so no screen does that arithmetic itself.

## Step 9 — Collect goods description and weight

The API requires both and the app does not currently ask. Add to
`booking_home_screen.dart`, below the drop picker:

- A `TextField` for goods description — required, max 255 chars
- A `TextField` for approximate weight in kg — numeric, required, > 0

Both are ephemeral form state, so `setState` in a `ConsumerStatefulWidget`, not
Riverpod. Convert the screen if it is currently a `ConsumerWidget`.

Disable the continue button until pickup, drop, description, and weight are all
present.

## Step 10 — Rewire the providers

**Edit `customer_app/lib/features/booking/application/booking_providers.dart`:**

```dart
final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(tokenProvider: ref.watch(authTokenProvider));
});

// Swapped from LocalFareEstimator. The local one stays for offline/tests.
final fareEstimatorProvider = Provider<FareEstimator>((ref) {
  return RemoteFareEstimator(ref.watch(apiClientProvider));
});

final bookingRepositoryProvider = Provider<BookingRepository>((ref) {
  return RemoteBookingRepository(ref.watch(apiClientProvider));
});
```

`fareEstimatesProvider` must become a `FutureProvider` — it is now a network
call, not a computation:

```dart
final fareEstimatesProvider = FutureProvider<List<FareEstimate>>((ref) async {
  final pickup = ref.watch(pickupLocationProvider);
  final drop = ref.watch(dropLocationProvider);
  if (pickup == null || drop == null) return const [];
  return ref.watch(fareEstimatorProvider).estimateAll(pickup, drop);
});
```

Also add providers for the goods description and weight if they need to cross
screens, or pass them as constructor arguments to the vehicle select screen —
constructor arguments are simpler and preferable here.

## Step 11 — Handle loading and error in `vehicle_select_screen.dart`

`ref.watch(fareEstimatesProvider)` now returns an `AsyncValue`. Use `.when`:

- **loading** — shimmer or spinner in place of the vehicle cards
- **error** — the `ApiException` message plus a Retry button calling
  `ref.invalidate(fareEstimatesProvider)`
- **data** — the existing cards

The offline case is the one most likely to happen in a demo, so make sure the
error state is legible rather than a red screen.

## Step 12 — Create a real booking on confirm

In whichever screen has the confirm action, replace the local simulation start
with a real call:

```dart
final booking = await ref
    .read(bookingRepositoryProvider)
    .create(/* ... */);
```

Then navigate to the status screen passing `booking.publicCode`.

Handle `ApiException` with a `SnackBar`. If `e.isUnauthorized`, call
`ref.read(sessionProvider.notifier).signOut()` — the token is dead and the app
should return to the phone screen rather than showing a confusing error.

Show a loading state on the button while the call is in flight, and guard
against double-taps: two taps creates two bookings.

## Step 13 — Status screen shows the real booking

`booking_status_screen.dart` takes a `publicCode`, fetches via
`bookingRepository.byPublicCode`, and displays the real status, public code,
addresses, goods, and quoted fare.

**Remove the fake timer progression and the fake driver roster.** The status
will sit at `pending` because no driver app exists yet — that is honest. Show
"Looking for a driver" with the booking code visible.

Add a manual refresh button. Automatic polling is spec 007.

## Step 14 — Verify on device

Start the server bound to all interfaces, not just loopback:

```powershell
cd $env:USERPROFILE\projects\volt\volt-backend
uvicorn app.main:app --reload --host 0.0.0.0
```

Windows Firewall will likely prompt — allow on **private networks only**.

Then, with the LAN IP from step 1:

```powershell
cd $env:USERPROFILE\projects\volt\customer_app
flutter run -d RMX3371 --dart-define=API_BASE_URL=http://YOUR_LAN_IP:8000
```

Confirm each:

| Test | Expected |
|---|---|
| Sign in, pick pickup + drop, enter goods, continue | Vehicle screen shows a spinner, then three fares |
| Fares match the server | Same numbers as `/docs` for the same route |
| Confirm a booking | Status screen with a real `VLT…` code |
| Check the database | Row exists with your `customer_id` |
| Turn WiFi off, retry estimate | Legible error + working Retry |
| Kill the server, retry | Same |

Database check:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -U postgres -d volt_dev -c "SELECT public_code, status, quoted_fare_paise, goods_description FROM bookings ORDER BY id DESC LIMIT 5;"
```

## Step 15 — Remove the temporary token print

Delete the `assert`-wrapped `ID_TOKEN=` debug print from `otp_screen.dart`
added in spec 005. It has served its purpose.

## Step 16 — Update `CLAUDE.md`

```
App talks to the API. Fares come from POST /bookings/estimate, bookings from
POST /bookings. LocalFareEstimator is display-only fallback; the server is
authoritative on price. Base URL injected via --dart-define=API_BASE_URL.
Cleartext HTTP allowed in debug source set only.
Run on device: flutter run -d RMX3371 --dart-define=API_BASE_URL=http://<lan-ip>:8000
Server must run with --host 0.0.0.0 for the phone to reach it.
```

## Step 17 — Report and stop

1. Files created, edited, deleted
2. The verification table with actual results
3. The fare numbers from the app and from `/docs` for the same route, side by
   side
4. The `public_code` created from the app and the psql row proving it persisted
5. Any deviation, and why

Do not add status polling or a driver-advance endpoint — that is spec 007.
