import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import 'config.dart';

http.Client buildHttpClient() {
  final inner = HttpClient();
  if (AppConfig.trustSelfSignedCertificates) {
    inner.badCertificateCallback = (cert, host, port) => true;
  }
  return IOClient(inner);
}
