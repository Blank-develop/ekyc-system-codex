import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'models.dart';

class EkycUpload {
  const EkycUpload.fromPath(
    this.path, {
    this.filename = 'capture.jpg',
    this.contentType = 'image/jpeg',
  }) : bytes = null;

  const EkycUpload.fromBytes(
    this.bytes, {
    this.filename = 'capture.jpg',
    this.contentType = 'image/jpeg',
  }) : path = null;

  final String? path;
  final Uint8List? bytes;
  final String filename;
  final String contentType;
}

class EkycApiException implements Exception {
  const EkycApiException({required this.statusCode, required this.detail});

  final int statusCode;
  final Object? detail;

  @override
  String toString() {
    final message = _readableErrorDetail(detail);
    if (message.isNotEmpty) return 'EkycApiException($statusCode): $message';
    return 'EkycApiException($statusCode)';
  }
}

class EkycClient {
  EkycClient({
    required String baseUrl,
    http.Client? httpClient,
    this.defaultTimeout = const Duration(seconds: 45),
    this.defaultRetries = 1,
  }) : _baseUri = Uri.parse(baseUrl.replaceFirst(RegExp(r'/$'), '')),
       _httpClient = httpClient ?? http.Client();

  final Uri _baseUri;
  final http.Client _httpClient;
  final Duration defaultTimeout;
  final int defaultRetries;

  Future<VerificationResult> createVerification(
    String userId, {
    int retries = 2,
    Duration? timeout,
  }) async {
    final json = await _requestJson(
      'POST',
      '/api/verifications',
      body: {'user_id': userId},
      retries: retries,
      timeout: timeout,
    );
    return VerificationResult.fromJson(json);
  }

  Future<VerificationResult> getVerification(
    String sessionId, {
    int? retries,
    Duration? timeout,
  }) async {
    final json = await _requestJson(
      'GET',
      '/api/verifications/$sessionId',
      retries: retries,
      timeout: timeout,
    );
    return VerificationResult.fromJson(json);
  }

  Future<VerificationResult> uploadDocument(
    String sessionId,
    EkycUpload image, {
    String? ocrText,
    int retries = 2,
    Duration timeout = const Duration(seconds: 90),
  }) async {
    final fields = ocrText == null ? null : {'ocr_text': ocrText};
    final json = await _requestMultipart(
      'POST',
      '/api/verifications/$sessionId/document',
      image,
      fields: fields,
      retries: retries,
      timeout: timeout,
    );
    return VerificationResult.fromJson(json);
  }

  Future<VerificationResult> completeChallenge(
    String sessionId,
    String challengeId, {
    bool passed = true,
    int retries = 2,
    Duration? timeout,
  }) async {
    final json = await _requestJson(
      'POST',
      '/api/verifications/$sessionId/challenge',
      body: {'challenge_id': challengeId, 'passed': passed},
      retries: retries,
      timeout: timeout,
    );
    return VerificationResult.fromJson(json);
  }

  Future<VerificationResult> analyzeSelfie(
    String sessionId,
    EkycUpload image, {
    int retries = 2,
    Duration timeout = const Duration(seconds: 90),
  }) async {
    final json = await _requestMultipart(
      'POST',
      '/api/verifications/$sessionId/selfie',
      image,
      retries: retries,
      timeout: timeout,
    );
    return VerificationResult.fromJson(json);
  }

  Future<FaceEnrollmentResponse> enrollFace(
    String sessionId, {
    int retries = 2,
    Duration timeout = const Duration(seconds: 60),
  }) async {
    final json = await _requestJson(
      'POST',
      '/api/verifications/$sessionId/enroll-face',
      retries: retries,
      timeout: timeout,
    );
    return FaceEnrollmentResponse.fromJson(json);
  }

  Future<FaceLoginResponse> faceLogin(
    EkycUpload image, {
    int retries = 2,
    Duration timeout = const Duration(seconds: 90),
  }) async {
    final json = await _requestMultipart(
      'POST',
      '/api/face-login',
      image,
      retries: retries,
      timeout: timeout,
    );
    return FaceLoginResponse.fromJson(json);
  }

  Future<UserProfileListResponse> listProfiles({
    int? retries,
    Duration? timeout,
  }) async {
    final json = await _requestJson(
      'GET',
      '/api/profiles',
      retries: retries,
      timeout: timeout,
    );
    return UserProfileListResponse.fromJson(json);
  }

  Future<DeleteProfileResponse> deleteProfile(
    String userId, {
    int? retries,
    Duration? timeout,
  }) async {
    final json = await _requestJson(
      'DELETE',
      '/api/profiles/${Uri.encodeComponent(userId)}',
      retries: retries,
      timeout: timeout,
    );
    return DeleteProfileResponse.fromJson(json);
  }

  Future<DeleteProfileResponse> deleteProfiles({
    int? retries,
    Duration? timeout,
  }) async {
    final json = await _requestJson(
      'DELETE',
      '/api/profiles',
      retries: retries,
      timeout: timeout,
    );
    return DeleteProfileResponse.fromJson(json);
  }

  void close() {
    _httpClient.close();
  }

  Future<JsonMap> _requestJson(
    String method,
    String path, {
    Map<String, Object?>? body,
    int? retries,
    Duration? timeout,
  }) async {
    return _withRetry(() async {
      final request = http.Request(method, _url(path));
      request.headers['Accept'] = 'application/json';
      if (body != null) {
        request.headers['Content-Type'] = 'application/json';
        request.body = jsonEncode(body);
      }
      final response = await _httpClient
          .send(request)
          .timeout(timeout ?? defaultTimeout)
          .then(http.Response.fromStream);
      return _parseResponse(response);
    }, retries: retries ?? defaultRetries);
  }

  Future<JsonMap> _requestMultipart(
    String method,
    String path,
    EkycUpload upload, {
    Map<String, String>? fields,
    int? retries,
    Duration? timeout,
  }) async {
    return _withRetry(() async {
      final request = http.MultipartRequest(method, _url(path));
      request.headers['Accept'] = 'application/json';
      if (fields != null) request.fields.addAll(fields);
      request.files.add(await _multipartFile(upload));
      final response = await _httpClient
          .send(request)
          .timeout(timeout ?? defaultTimeout)
          .then(http.Response.fromStream);
      return _parseResponse(response);
    }, retries: retries ?? defaultRetries);
  }

  Future<JsonMap> _withRetry(
    Future<JsonMap> Function() action, {
    required int retries,
  }) async {
    Object? lastError;
    for (var attempt = 0; attempt <= retries; attempt += 1) {
      try {
        return await action();
      } on EkycApiException {
        rethrow;
      } on TimeoutException catch (error) {
        lastError = error;
      } on http.ClientException catch (error) {
        lastError = error;
      }
      if (attempt < retries) {
        await Future<void>.delayed(_retryDelay(attempt));
      }
    }
    throw lastError ?? StateError('eKYC request failed.');
  }

  Future<http.MultipartFile> _multipartFile(EkycUpload upload) {
    final contentType = MediaType.parse(upload.contentType);
    if (upload.path != null) {
      return http.MultipartFile.fromPath(
        'file',
        upload.path!,
        filename: upload.filename,
        contentType: contentType,
      );
    }
    final bytes = upload.bytes;
    if (bytes == null) {
      throw ArgumentError('EkycUpload requires either path or bytes.');
    }
    return Future.value(
      http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: upload.filename,
        contentType: contentType,
      ),
    );
  }

  Uri _url(String path) {
    return _baseUri.replace(path: _joinPath(_baseUri.path, path));
  }
}

JsonMap _parseResponse(http.Response response) {
  final body = response.body.isEmpty
      ? <String, dynamic>{}
      : jsonDecode(response.body) as Object?;
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw EkycApiException(statusCode: response.statusCode, detail: body);
  }
  if (body is Map<String, dynamic>) return body;
  if (body is Map) return Map<String, dynamic>.from(body);
  return <String, dynamic>{};
}

String _joinPath(String basePath, String path) {
  final left = basePath.endsWith('/')
      ? basePath.substring(0, basePath.length - 1)
      : basePath;
  final right = path.startsWith('/') ? path : '/$path';
  return '$left$right';
}

Duration _retryDelay(int attempt) {
  return Duration(milliseconds: attempt == 0 ? 900 : 2200);
}

String _readableErrorDetail(Object? detail) {
  if (detail is String) return detail;
  if (detail is Map && detail['detail'] != null) {
    return detail['detail'].toString();
  }
  return '';
}
