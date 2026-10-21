# Run the customer app against the DEPLOYED backend.
#
#   .\run-prod.ps1                 # uses $env:VOLT_DEVICE
#   .\run-prod.ps1 -Device RMX3371
#
# THIS WRITES REAL ROWS TO THE REAL DATABASE. There is no staging - one
# backend, one database, one Firebase project, shared by both people. Use
# run-local.ps1 for anything experimental.
#
# The device id used to be hardcoded to RMX3371, which failed for anyone else
# with an unhelpful Flutter error. Set it once per machine:
#   $env:VOLT_DEVICE = 'RMX3371'        # `flutter devices` lists the ids
#
# No LAN IP needed here - the URL below is the deployed backend. Expect the
# first request to take up to 60s: Render's free plan spins down when idle.

param(
    [string]$Device = $env:VOLT_DEVICE,
    [string]$ApiBaseUrl = 'https://volt-api-951s.onrender.com'
)

if (-not $Device) {
    Write-Error @'
No device. Set VOLT_DEVICE or pass -Device.

    $env:VOLT_DEVICE = 'RMX3371'
    .\run-prod.ps1

Run `flutter devices` to see the ids of what is attached.
'@
    exit 1
}

Write-Host "customer_app -> $ApiBaseUrl on $Device  (PRODUCTION)" -ForegroundColor Yellow

flutter run -d $Device --dart-define=API_BASE_URL=$ApiBaseUrl
