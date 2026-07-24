/// KyronPay demo configuration.
///
/// Point the app at your Kyron server with:
///   flutter run --dart-define=KYRON_BASE_URL=https://192.168.100.253:8090
class AppConfig {
  static const baseUrl = String.fromEnvironment(
    'KYRON_BASE_URL',
    defaultValue: 'https://192.168.100.253:8090',
  );

  /// The hosted eKYC registration flow (Kyron web app) -- opened in the
  /// system browser, like a hosted checkout page.
  static String get registrationUrl => baseUrl;

  /// DEMO ONLY: the local Kyron dev server uses a self-signed certificate,
  /// so the demo trusts it explicitly. A production integration talks to a
  /// properly-certified endpoint and must never do this.
  static const trustSelfSignedCertificates = true;
}
