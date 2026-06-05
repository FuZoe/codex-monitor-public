param(
  [ValidateSet("thinking", "working", "testing", "blocked", "done")]
  [string]$Status = "working",
  [string]$Title = "",
  [string]$Task = "Codex is working on the current task",
  [int]$FiveHourUsed = 0,
  [int]$FiveHourLimit = 100,
  [int]$WeeklyUsed = 0,
  [int]$WeeklyLimit = 500,
  [int]$FiveHourRemainingPercent = -1,
  [int]$WeeklyRemainingPercent = -1,
  [string]$Unit = "messages",
  [string]$Turn = "Current thread"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$path = Join-Path $repoRoot "desktop\codex-status.json"
$now = Get-Date -Format "o"

if ($Title -eq "") {
  $Title = switch ($Status) {
    "thinking" { "Thinking" }
    "working" { "Working" }
    "testing" { "Testing" }
    "blocked" { "Blocked" }
    "done" { "Done" }
  }
}

if ($FiveHourRemainingPercent -ge 0) {
  $bounded = [Math]::Max(0, [Math]::Min(100, $FiveHourRemainingPercent))
  $FiveHourLimit = 100
  $FiveHourUsed = 100 - $bounded
  $Unit = "%"
}

if ($WeeklyRemainingPercent -ge 0) {
  $bounded = [Math]::Max(0, [Math]::Min(100, $WeeklyRemainingPercent))
  $WeeklyLimit = 100
  $WeeklyUsed = 100 - $bounded
  $Unit = "%"
}

$previous = $null
if (Test-Path $path) {
  try {
    $previous = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
  } catch {
    $previous = $null
  }
}

$startedAt = if ($previous -and $previous.startedAt) { $previous.startedAt } else { $now }
$oldLog = @()
if ($previous -and $previous.log) {
  $oldLog = @($previous.log | Select-Object -First 7)
}

$state = [ordered]@{
  status = $Status
  title = $Title
  task = $Task
  turn = $Turn
  quotas = @(
    [ordered]@{
      id = "five_hour"
      label = "5-hour limit"
      used = $FiveHourUsed
      limit = $FiveHourLimit
      unit = $Unit
      resetAt = ""
      quotaSource = "manual"
      quotaUpdatedAt = $now
    },
    [ordered]@{
      id = "weekly"
      label = "Weekly limit"
      used = $WeeklyUsed
      limit = $WeeklyLimit
      unit = $Unit
      resetAt = ""
      quotaSource = "manual"
      quotaUpdatedAt = $now
    }
  );
  updatedAt = $now
  startedAt = $startedAt
  log = @(
    [ordered]@{
      time = $now
      text = "$Title - $Task"
    }
  ) + $oldLog;
}

$json = $state | ConvertTo-Json -Depth 5
$encoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($path, $json, $encoding)
Write-Host "Updated $path"
