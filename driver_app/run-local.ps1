# LAN IP is per-machine — update to match whatever `ipconfig` shows for the
# machine running the backend. Server must run with --host 0.0.0.0.
flutter run -d RMX3371 --dart-define=API_BASE_URL=http://192.168.1.8:8000
