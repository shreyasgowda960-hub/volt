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
  /// Almost every endpoint returns `detail` as a plain string and this stays
  /// null. The exception is the two driver-auth 403s (spec 017), which the
  /// driver app ROUTES on — branching on prose meant a copy-edit to a
  /// user-facing sentence could silently change which screen a driver saw.
  /// Branch on this when it is present; never on [message].
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

    // `detail` takes three shapes and all three are read here, so no caller
    // has to know which one its endpoint sent:
    //   - a plain string, almost everywhere;
    //   - an object with `code` and `message`, on the two driver-auth 403s;
    //   - a LIST of field errors, from FastAPI's own request validation,
    //     which is for a developer and must never reach a driver.
    final detail = e.response?.data is Map
        ? (e.response!.data as Map)['detail']
        : null;

    if (detail is Map) {
      final message = detail['message'];
      final code = detail['code'];
      return ApiException(
        message is String ? message : 'Something went wrong.',
        statusCode: status,
        code: code is String ? code : null,
      );
    }

    if (detail is String) {
      return ApiException(detail, statusCode: status);
    }

    // 422 used to be blanket-generic, which also swallowed the DELIBERATE
    // 422s — vehicle capacity, and spec 017's "Upload a JPG, PNG or PDF."
    // Those carry a string detail and are handled above; only FastAPI's own
    // validation list reaches here, and that one genuinely has nothing a
    // user can act on.
    if (status == 422) {
      return const ApiException('Something in that request was invalid.',
          statusCode: 422);
    }

    return ApiException('Something went wrong.', statusCode: status);
  }
}
