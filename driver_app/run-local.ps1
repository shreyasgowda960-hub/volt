# Run the driver app against a LOCAL backend on your LAN.
#
#   .\run-local.ps1                 # uses $env:VOLT_DEVICE
#   .\run-local.ps1 -Device RMX3371 # or name the device explicitly
#
# Nothing here is hardcoded to one machine any more. Both the device and the
# LAN IP used to be baked in (RMX3371, 192.168.1.8), which worked for exactly
# one person on exactly one network - the second person got a Flutter error
# about an unknown device, or an app that silently could not reach the server.
#
# Set these once, per machine:
#   $env:VOLT_DEVICE = 'RMX3371'        # `flutter devices` lists the ids
#   $env:VOLT_LAN_IP = '192.168.1.8'    # `ipconfig` -> IPv4 of THIS machine
#
# To make them stick across terminals:
#   [Environment]::SetEnvironmentVariable('VOLT_LAN_IP','192.168.1.8','User')
#
# The backend must be listening on all interfaces, or the phone cannot reach
# it even with the right IP:
#   uvicorn app.main:app --reload --host 0.0.0.0

param(
    [string]$Device = $env:VOLT_DEVICE,
    [string]$LanIp  = $env:VOLT_LAN_IP
)

if (-not $Device) {
    Write-Error @'
No device. Set VOLT_DEVICE or pass -Device.

    $env:VOLT_DEVICE = 'RMX3371'
    .\run-local.ps1

Run `flutter devices` to see the ids of what is attached.
'@
    exit 1
}

if (-not $LanIp) {
    Write-Error @'
No LAN IP. Set VOLT_LAN_IP or pass -LanIp.

    $env:VOLT_LAN_IP = '192.168.1.8'
    .\run-local.ps1

This is the IPv4 address of the machine RUNNING THE BACKEND, from `ipconfig`
- not the phone's. The phone and this machine must be on the same network,
and the server must be started with --host 0.0.0.0.
'@
    exit 1
}

$baseUrl = "http://${LanIp}:8000"
Write-Host "driver_app -> $baseUrl on $Device" -ForegroundColor Cyan

flutter run -d $Device --dart-define=API_BASE_URL=$baseUrl
