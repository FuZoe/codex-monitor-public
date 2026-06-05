param(
  [string]$SdkRoot = "$env:LOCALAPPDATA\Android\Sdk",
  [string]$BuildTools = "35.0.1",
  [string]$Platform = "android-35"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$root = Join-Path $repoRoot "android"
$build = Join-Path $root "build"
$gen = Join-Path $build "gen"
$classes = Join-Path $build "classes"
$dex = Join-Path $build "dex"
$unsigned = Join-Path $build "codex-monitor-unsigned.apk"
$aligned = Join-Path $build "codex-monitor-aligned.apk"
$dist = Join-Path $repoRoot "dist"
$apk = Join-Path $dist "codex-monitor-android.apk"
$androidJar = Join-Path $SdkRoot "platforms\$Platform\android.jar"
$aapt2 = Join-Path $SdkRoot "build-tools\$BuildTools\aapt2.exe"
$d8 = Join-Path $SdkRoot "build-tools\$BuildTools\d8.bat"
$zipalign = Join-Path $SdkRoot "build-tools\$BuildTools\zipalign.exe"
$apksigner = Join-Path $SdkRoot "build-tools\$BuildTools\apksigner.bat"
$keystore = Join-Path $build "debug.keystore"

function Invoke-Checked {
  param(
    [string]$File,
    [string[]]$Arguments
  )
  & $File @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$File failed with exit code $LASTEXITCODE"
  }
}

Remove-Item -LiteralPath $build -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $gen, $classes, $dex, $dist | Out-Null

Invoke-Checked $aapt2 @("compile", "--dir", (Join-Path $root "res"), "-o", (Join-Path $build "res.zip"))
Invoke-Checked $aapt2 @("link", "-I", $androidJar, "--manifest", (Join-Path $root "AndroidManifest.xml"), "--java", $gen, "-o", $unsigned, (Join-Path $build "res.zip"))

$sources = @(
  (Join-Path $root "src\com\codexmonitor\MainActivity.java"),
  (Join-Path $gen "com\codexmonitor\R.java")
)

javac -encoding UTF-8 -source 1.8 -target 1.8 -bootclasspath $androidJar -d $classes $sources
if ($LASTEXITCODE -ne 0) {
  throw "javac failed with exit code $LASTEXITCODE"
}

$classFiles = @(Get-ChildItem -LiteralPath $classes -Recurse -Filter *.class | ForEach-Object { $_.FullName })
Invoke-Checked $d8 (@("--release", "--min-api", "23", "--output", $dex) + $classFiles)
jar uf $unsigned -C $dex classes.dex
if ($LASTEXITCODE -ne 0) {
  throw "jar failed with exit code $LASTEXITCODE"
}
Invoke-Checked $zipalign @("-f", "4", $unsigned, $aligned)

keytool -genkeypair -v -keystore $keystore -storepass android -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Codex Monitor,O=Codex,C=US" | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "keytool failed with exit code $LASTEXITCODE"
}
Invoke-Checked $apksigner @("sign", "--ks", $keystore, "--ks-pass", "pass:android", "--key-pass", "pass:android", "--out", $apk, $aligned)
Invoke-Checked $apksigner @("verify", $apk)

Write-Host "Built $apk"
