param(
  [int]$Port = 8767,
  [int]$DiscoveryPort = 45777
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$desktopRoot = Join-Path $repoRoot "desktop"
$script = Join-Path $desktopRoot "codex-monitor-server.py"

python $script --port $Port --discovery-port $DiscoveryPort --root $desktopRoot
