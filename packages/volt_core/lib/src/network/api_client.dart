import 'package:dio/dio.dart';

import '../auth/auth_token_provider.dart';
import '../config/app_config.dart';

/// Thrown for anything the UI should show a message for.
class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode, this.code});

  final String message;
  final int? statusCode;

  /// A machine-readable reason, when the server sent one.
  ///
  /// Arrives as a TOP-LEVEL sibling of `detail`, never in place of it, so a
  /// server that does not send one simply leaves this null and [message] still
  /// works. Only the two driver-auth 403s carry one today (spec 017), because
  /// the driver app routes on which of them it got and branching on prose
  /// meant a copy-edit to a user-facing sentence could change which screen a
  /// driver saw.
  ///
  /// NEVER assume this is non-null just because the endpoint is meant to send
  /// one. The apps ship independently of the backend, so an app newer than the
  /// server it is talking to is routine — that exact skew put drivers on a
  /// dead-end error screen once already.
  final String? code;

  bool get isUnauthorized => statusCode == 401;

  @override
  String toString() => 'ApiException($statusCode${code == null ? '' : '/$code'}): $message';
}

class ApiClient {
  ApiClient({required AuthTokenProvider tokenProvider, Dio? dio})
      : _tokenProvider = tokenProvider,
        _dio = dio ?? Dio() {
    _dio.options
      ..baseUrl = AppConfig.apiBaseUrl
      ..connectTimeout = Duration(seconds: AppConfig.isRemote ? 60 : 10)
      ..receiveTimeout = Duration(seconds: AppConfig.isRemote ? 60 : 15)
      // Generous, and deliberately not tied to isRemote: this bounds how long
      // we spend PUSHING bytes, and the thing that makes it slow is the
      // driver's uplink, not where the server is. A multi-megabyte document
      // photo on a weak mobile connection needs far longer than a JSON body.
      // Only postMultipart sends enough data for this to matter.
      ..sendTimeout = const Duration(seconds: 120)
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

  Future<List<dynamic>> getList(String path) async {
    try {
      final response = await _dio.get<List<dynamic>>(path);
      return response.data ?? <dynamic>[];
    } on DioException catch (e) {
      throw _translate(e);
    }
  }

  Future<Map<String, dynamic>> patch(
    String path,
    Map<String, dynamic> body,
  ) async {
    try {
      final response = await _dio.patch<Map<String, dynamic>>(path, data: body);
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw _translate(e);
    }
  }

  /// Multipart POST, for file upload. The only caller today is the driver
  /// document upload (spec 017).
  ///
  /// [bytes] rather than a path on purpose: the caller has already read and
  /// possibly downscaled the image, and the server sniffs the LEADING BYTES
  /// to decide the real content type — so what we declare here is a courtesy
  /// to logs, not something the backend trusts.
  Future<Map<String, dynamic>> postMultipart(
    String path, {
    required Map<String, String> fields,
    required String fileField,
    required List<int> bytes,
    required String filename,
  }) async {
    try {
      final form = FormData.fromMap({
        ...fields,
        fileField: MultipartFile.fromBytes(bytes, filename: filename),
      });

      final response = await _dio.post<Map<String, dynamic>>(
        path,
        data: form,
        // The client-wide default is application/json. Dio only writes the
        // multipart boundary when the request's own content type says
        // multipart, so without this override the server receives a body it
        // cannot parse at all.
        options: Options(contentType: Headers.multipartFormDataContentType),
      );
      return response.data ?? <String, dynamic>{};
    } on DioException catch (e) {
      throw _translate(e);
    }
  }

  ApiException _translate(DioException e) {
    final status = e.response?.statusCode;

    if (e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.sendTimeout ||
        e.type == DioExceptionType.connectionError) {
      return const ApiException(
        'Cannot reach VOLT. Check your connection and try again.',
      );
    }
    if (status == 401) {
      return const ApiException('Session expired. Please sign in again.',
          statusCode: 401);
    }
    if (status != null && status >= 500) {
      return ApiException('VOLT is having trouble. Try again shortly.',
          statusCode: status);
    }

    final body = e.response?.data is Map ? e.response!.data as Map : null;

    // `detail` is ALWAYS a plain string when the server sends one, with the
    // single exception of FastAPI's own request-validation errors, where it is
    // a LIST of field errors meant for a developer and never for a driver.
    final detail = body?['detail'];

    // Optional sibling, absent on every server that predates it. Read
    // defensively for exactly that reason.
    final rawCode = body?['code'];
    final code = rawCode is String ? rawCode : null;

    if (detail is String) {
      return ApiException(detail, statusCode: status, code: code);
    }

    // 422 used to be blanket-generic, which also swallowed the DELIBERATE
    // 422s — vehicle capacity, and spec 017's "Upload a JPG, PNG or PDF."
    // Those carry a string detail and are handled above; only the validation
    // list reaches here, and that one genuinely has nothing a user can act on.
    if (status == 422) {
      return ApiException('Something in that request was invalid.',
          statusCode: 422, code: code);
    }

    return ApiException('Something went wrong.', statusCode: status, code: code);
  }
}
