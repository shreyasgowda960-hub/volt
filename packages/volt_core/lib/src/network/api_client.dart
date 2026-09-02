import 'package:dio/dio.dart';

import '../auth/auth_token_provider.dart';
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
      ..connectTimeout = Duration(seconds: AppConfig.isRemote ? 60 : 10)
      ..receiveTimeout = Duration(seconds: AppConfig.isRemote ? 60 : 15)
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
