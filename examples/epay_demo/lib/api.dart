import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:laligence_ekyc/laligence_ekyc.dart';

import 'config.dart';
import 'http_client.dart';

/// Shared HTTP client. For the demo it trusts the dev server's self-signed
/// certificate (see [AppConfig.trustSelfSignedCertificates]).
final http.Client httpClient = buildHttpClient();

/// The Kyron eKYC SDK client -- exactly what a fintech customer would embed.
final EkycClient ekyc = EkycClient(
  baseUrl: AppConfig.baseUrl,
  httpClient: httpClient,
);

// ---------------------------------------------------------------------------
// Demo wallet API (the toy ledger the Kyron server exposes when
// LALIGENCE_DEMO_WALLET=1). In a real integration this half would be the
// customer's own payments backend.
// ---------------------------------------------------------------------------

class WalletTransaction {
  const WalletTransaction({
    required this.kind,
    required this.amountCents,
    required this.counterparty,
    required this.at,
    this.note,
  });

  factory WalletTransaction.fromJson(Map<String, dynamic> json) =>
      WalletTransaction(
        kind: json['kind'] as String,
        amountCents: json['amount_cents'] as int,
        counterparty: json['counterparty'] as String,
        note: json['note'] as String?,
        at: json['at'] as String,
      );

  final String kind;
  final int amountCents;
  final String counterparty;
  final String? note;
  final String at;
}

class Wallet {
  const Wallet({
    required this.userId,
    required this.displayName,
    required this.balanceCents,
    required this.currency,
    required this.transactions,
  });

  factory Wallet.fromJson(Map<String, dynamic> json) => Wallet(
    userId: json['user_id'] as String,
    displayName: json['display_name'] as String,
    balanceCents: json['balance_cents'] as int,
    currency: json['currency'] as String? ?? 'USD',
    transactions: ((json['transactions'] as List<dynamic>?) ?? [])
        .map((item) => WalletTransaction.fromJson(item as Map<String, dynamic>))
        .toList(),
  );

  final String userId;
  final String displayName;
  final int balanceCents;
  final String currency;
  final List<WalletTransaction> transactions;
}

class WalletHolder {
  const WalletHolder({required this.userId, required this.displayName});

  factory WalletHolder.fromJson(Map<String, dynamic> json) => WalletHolder(
    userId: json['user_id'] as String,
    displayName: json['display_name'] as String,
  );

  final String userId;
  final String displayName;
}

class WalletApiException implements Exception {
  const WalletApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

class WalletApi {
  WalletApi(this._client);

  final http.Client _client;

  Uri _url(String path) =>
      Uri.parse('${AppConfig.baseUrl}/api/demo-wallet$path');

  Future<Wallet> claim(String userId) => _post('/claim', {'user_id': userId});

  Future<Wallet> wallet(String userId) async {
    final response = await _client.get(_url('/${Uri.encodeComponent(userId)}'));
    return Wallet.fromJson(_parse(response));
  }

  Future<List<WalletHolder>> holders() async {
    final response = await _client.get(_url('/holders'));
    final json = _parse(response);
    return ((json['holders'] as List<dynamic>?) ?? [])
        .map((item) => WalletHolder.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<Wallet> transfer({
    required String fromUserId,
    required String toUserId,
    required int amountCents,
    String? note,
  }) => _post('/transfer', {
    'from_user_id': fromUserId,
    'to_user_id': toUserId,
    'amount_cents': amountCents,
    if (note != null && note.isNotEmpty) 'note': note,
  });

  Future<Wallet> _post(String path, Map<String, dynamic> body) async {
    final response = await _client.post(
      _url(path),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    return Wallet.fromJson(_parse(response));
  }

  Map<String, dynamic> _parse(http.Response response) {
    final Map<String, dynamic> json;
    try {
      json =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {
      throw WalletApiException(
        'Unexpected server response (${response.statusCode}).',
      );
    }
    if (response.statusCode >= 400) {
      throw WalletApiException((json['detail'] ?? 'Request failed').toString());
    }
    return json;
  }
}

final WalletApi walletApi = WalletApi(httpClient);
