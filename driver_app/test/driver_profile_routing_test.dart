@TestOn('vm')
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:volt_core/volt_core.dart';

import 'package:driver_app/features/driver/application/driver_providers.dart';
import 'package:driver_app/features/driver/data/driver_repository.dart';

/// Routing regression test for the driver-with-no-profile case.
///
/// THE BODIES HERE ARE RECORDED, NOT WRITTEN. test/fixtures/drivers_me_403.json
/// holds the literal response text two real FastAPI apps returned over real
/// HTTP requests — this branch, and the revision that was deployed to
/// production when the bug was found. Nothing in this file types out a body by
/// hand.
///
/// That is deliberate. The last several bugs in this project were all fixtures
/// that did not look like production, and this one was exactly that shape: the
/// app was changed to require a `code` field, every test passed against a
/// server that sent one, and the server in production did not. A test written
/// from the new server's shape could not have caught it, because the shape it
/// would have asserted was the shape that worked.
void main() {
  late Map<String, dynamic> fixtures;

  setUpAll(() {
    final file = File('test/fixtures/drivers_me_403.json');
    fixtures = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  });

  /// An ApiClient whose transport replays one recorded response.
  ///
  /// The real Dio error path runs: Dio builds the DioException, and
  /// ApiClient._translate parses it. Only the socket is replaced.
  ApiClient clientReplaying(Map<String, dynamic> recorded) {
    final dio = Dio()
      ..httpClientAdapter = _ReplayAdapter(
        statusCode: recorded['status'] as int,
        body: recorded['body'] as String,
      );
    return ApiClient(tokenProvider: _StubTokenProvider(), dio: dio);
  }

  ProviderContainer containerFor(Map<String, dynamic> recorded) {
    final container = ProviderContainer(
      overrides: [
        driverRepositoryProvider.overrideWithValue(
          RemoteDriverRepository(clientReplaying(recorded)),
        ),
      ],
    );
    addTearDown(container.dispose);
    return container;
  }

  group('a 403 for a uid with no driver row', () {
    // The regression. Before the fix this returned an AsyncError carrying an
    // ApiException, and _ProfileGate rendered its dead-end error screen
    // instead of DriverRegistrationScreen.
    test('routes to registration against the DEPLOYED server (no code field)',
        () async {
      final container = containerFor(
        fixtures['legacy'] as Map<String, dynamic>,
      );

      final profile = await container.read(driverProfileProvider.future);

      expect(
        profile,
        isNull,
        reason: 'null is the routing signal for "show registration". An '
            'ApiException here puts the driver on the error screen.',
      );
    });

    test('routes to registration against the CODED server', () async {
      final container = containerFor(
        fixtures['coded'] as Map<String, dynamic>,
      );

      final profile = await container.read(driverProfileProvider.future);

      expect(profile, isNull);
    });

    test('the repository raises DriverNotRegistered for both shapes', () async {
      for (final key in ['legacy', 'coded']) {
        final repo = RemoteDriverRepository(
          clientReplaying(fixtures[key] as Map<String, dynamic>),
        );
        await expectLater(
          repo.me(),
          throwsA(isA<DriverNotRegistered>()),
          reason: '$key shape must resolve to the routing signal',
        );
      }
    });
  });

  group('the recorded fixtures still describe what they claim', () {
    // Guards the test itself. If someone regenerates these and the shapes have
    // drifted, the tests above could start passing for the wrong reason — the
    // legacy case silently becoming a second copy of the coded one.
    test('legacy carries no code and coded carries one', () {
      final legacy =
          jsonDecode((fixtures['legacy'] as Map)['body'] as String) as Map;
      final coded =
          jsonDecode((fixtures['coded'] as Map)['body'] as String) as Map;

      expect(legacy.containsKey('code'), isFalse,
          reason: 'the legacy body is the one WITHOUT a code; that is the '
              'whole point of keeping it');
      expect(coded['code'], 'driver_not_registered');
    });

    test('detail is a plain string in BOTH, so old apps keep working', () {
      for (final key in ['legacy', 'coded']) {
        final body =
            jsonDecode((fixtures[key] as Map)['body'] as String) as Map;
        expect(
          body['detail'],
          isA<String>(),
          reason: 'spec 017 briefly made detail an object. That breaks every '
              'already-sideloaded APK, which cannot be force-updated, so the '
              'code must stay a SIBLING of detail rather than replace it.',
        );
      }
    });
  });

  group('ApiException.code', () {
    test('is null when the server sends no code, not an empty string', () {
      final client = clientReplaying(fixtures['legacy'] as Map<String, dynamic>);

      expect(
        () async => client.get('/api/v1/drivers/me'),
        throwsA(
          isA<ApiException>()
              .having((e) => e.code, 'code', isNull)
              .having((e) => e.statusCode, 'statusCode', 403)
              .having((e) => e.message, 'message', 'Not registered as a driver'),
        ),
      );
    });

    test('is populated when the server sends one', () {
      final client = clientReplaying(fixtures['coded'] as Map<String, dynamic>);

      expect(
        () async => client.get('/api/v1/drivers/me'),
        throwsA(
          isA<ApiException>()
              .having((e) => e.code, 'code', 'driver_not_registered')
              .having((e) => e.message, 'message', 'Not registered as a driver'),
        ),
      );
    });
  });
}

/// Replays one recorded response for any request.
class _ReplayAdapter implements HttpClientAdapter {
  _ReplayAdapter({required this.statusCode, required this.body});

  final int statusCode;
  final String body;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromString(
      body,
      statusCode,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class _StubTokenProvider implements AuthTokenProvider {
  @override
  Future<String?> currentToken() async => 'stub-token';
}
