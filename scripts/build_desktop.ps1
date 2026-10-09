param(
  [ValidateSet('all', 'nsis', 'msi')]
  [string]$BundleTarget = 'all'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$tauriCli = Join-Path $projectRoot 'frontend\node_modules\.bin\tauri.cmd'
$envFile = Join-Path $projectRoot '.env'
$userProfilePath = [Environment]::GetFolderPath('UserProfile')
$modelCache = Join-Path $userProfilePath '.cache\huggingface\hub\models--BAAI--bge-small-zh'
$pyInstallerRoot = Join-Path $projectRoot 'build\pyinstaller'
$pyInstallerDist = Join-Path $pyInstallerRoot 'dist'
$pyInstallerWork = Join-Path $pyInstallerRoot 'work'
$pyInstallerSpec = Join-Path $pyInstallerRoot 'spec'
$targetTriple = 'x86_64-pc-windows-msvc'
$sidecarName = "desktop-backend-$targetTriple"
$sidecarDirectory = Join-Path $projectRoot 'src-tauri\binaries'
$sidecarPath = Join-Path $sidecarDirectory "$sidecarName.exe"
$releaseDirectory = Join-Path $projectRoot 'release'
$desktopResourceRoot = Join-Path $projectRoot 'build\desktop-resources'
$libreOfficeSource = $env:LIBREOFFICE_RUNTIME_DIR
$previewFontSource = $env:PREVIEW_FONT_DIR

if (-not $libreOfficeSource) {
  throw 'LIBREOFFICE_RUNTIME_DIR must point to the fixed, redistributable LibreOffice runtime used for the desktop bundle.'
}
if (-not $previewFontSource) {
  throw 'PREVIEW_FONT_DIR must point to the redistributable fonts used for stable PDF previews.'
}
$libreOfficeSource = (Resolve-Path -LiteralPath $libreOfficeSource).Path
$previewFontSource = (Resolve-Path -LiteralPath $previewFontSource).Path
$sofficePath = Join-Path $libreOfficeSource 'program\soffice.exe'
if (-not (Test-Path -LiteralPath $sofficePath)) {
  throw "LibreOffice runtime is missing program\soffice.exe: $sofficePath"
}
if (-not (Get-ChildItem -LiteralPath $previewFontSource -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)) {
  throw "Preview font directory is empty: $previewFontSource"
}

foreach ($requiredPath in @($python, $tauriCli, $envFile, $modelCache)) {
  if (-not (Test-Path -LiteralPath $requiredPath)) {
    throw "Missing desktop build dependency: $requiredPath"
  }
}

New-Item -ItemType Directory -Force -Path $pyInstallerDist, $pyInstallerWork, $pyInstallerSpec, $sidecarDirectory, $releaseDirectory, $desktopResourceRoot | Out-Null

$bundledLibreOffice = Join-Path $desktopResourceRoot 'libreoffice'
$bundledFonts = Join-Path $desktopResourceRoot 'fonts'
if (Test-Path -LiteralPath $bundledLibreOffice) { Remove-Item -LiteralPath $bundledLibreOffice -Recurse -Force }
if (Test-Path -LiteralPath $bundledFonts) { Remove-Item -LiteralPath $bundledFonts -Recurse -Force }
Copy-Item -LiteralPath $libreOfficeSource -Destination $bundledLibreOffice -Recurse -Force
Copy-Item -LiteralPath $previewFontSource -Destination $bundledFonts -Recurse -Force
if (-not (Test-Path -LiteralPath (Join-Path $bundledLibreOffice 'program\soffice.exe'))) { throw 'Bundled LibreOffice validation failed.' }
if (-not (Get-ChildItem -LiteralPath $bundledFonts -File -Recurse | Select-Object -First 1)) { throw 'Bundled font validation failed.' }

$pyInstallerArguments = @(
  '-m', 'PyInstaller',
  '--noconfirm',
  '--clean',
  '--onefile',
  '--windowed',
  '--noupx',
  '--name', $sidecarName,
  '--distpath', $pyInstallerDist,
  '--workpath', $pyInstallerWork,
  '--specpath', $pyInstallerSpec,
  '--paths', $projectRoot,
  '--add-data', "$envFile;.",
  '--add-data', "$(Join-Path $projectRoot 'vector_db');vector_db",
  '--add-data', "$(Join-Path $projectRoot 'data');data",
  '--add-data', "$(Join-Path $projectRoot 'ppt');ppt",
  '--add-data', "$modelCache;model_cache\hub\models--BAAI--bge-small-zh",
  '--collect-all', 'sentence_transformers',
  '--collect-all', 'transformers',
  '--collect-all', 'huggingface_hub',
  '--collect-all', 'faiss',
  '--collect-submodules', 'uvicorn',
  '--collect-submodules', 'multipart',
  '--copy-metadata', 'sentence-transformers',
  '--copy-metadata', 'transformers',
  '--copy-metadata', 'huggingface-hub',
  '--copy-metadata', 'openai',
  (Join-Path $projectRoot 'scripts\desktop_backend.py')
)

Push-Location $projectRoot
try {
  & $python @pyInstallerArguments
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed: $LASTEXITCODE" }

  $builtSidecar = Join-Path $pyInstallerDist "$sidecarName.exe"
  Copy-Item -LiteralPath $builtSidecar -Destination $sidecarPath -Force

  & npm.cmd --prefix frontend run build
  if ($LASTEXITCODE -ne 0) { throw "Vue production build failed: $LASTEXITCODE" }

  $vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
  $vsInstallPath = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
  if (-not $vsInstallPath) { throw 'Visual Studio C++ Build Tools not found.' }
  $devShellModule = Join-Path $vsInstallPath 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll'
  Import-Module $devShellModule
  Enter-VsDevShell -VsInstallPath $vsInstallPath -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null

  $env:PATH = (Join-Path $userProfilePath '.cargo\bin') + ';' + $env:PATH
  $proxyListener = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq 7897 }
  if ($proxyListener) {
    $env:HTTP_PROXY = 'http://127.0.0.1:7897'
    $env:HTTPS_PROXY = 'http://127.0.0.1:7897'
  }

  $bundleArgument = if ($BundleTarget -eq 'all') { 'nsis,msi' } else { $BundleTarget }
  & $tauriCli build --config (Join-Path $projectRoot 'src-tauri\tauri.conf.json') --target $targetTriple --bundles $bundleArgument
  if ($LASTEXITCODE -ne 0) { throw "Tauri installer build failed: $LASTEXITCODE" }

  $bundleRoot = Join-Path $projectRoot "src-tauri\target\$targetTriple\release\bundle"
  $installers = @(Get-ChildItem -LiteralPath $bundleRoot -File -Recurse | Where-Object { $_.Extension -in @('.exe', '.msi') })
  if (-not $installers) { throw 'Tauri build completed without installer output.' }
  foreach ($installer in $installers) {
    Copy-Item -LiteralPath $installer.FullName -Destination (Join-Path $releaseDirectory $installer.Name) -Force
  }

  $installers | ForEach-Object {
    Write-Output ("{0} ({1:N2} MiB)" -f (Join-Path $releaseDirectory $_.Name), ($_.Length / 1MB))
  }
}
finally {
  Pop-Location
}
