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

  // Render's free plan sleeps when idle and cold-starts in 30-60s; a local
  // dev server that isn't answering in 10s is just down. ApiClient and the
  // vehicle select screen both key off this rather than the raw string.
  static bool get isRemote => apiBaseUrl.startsWith('https');
}
