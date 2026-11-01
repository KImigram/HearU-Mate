param(
    [string]$Version = "0.1.0",
    [string]$Python = "D:\apps\anaconda\envs\meeting_onnx\python.exe",
    [string]$ModelRoot = "D:\models\sherpa-onnx",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$branch = (& git -C $projectRoot branch --show-current).Trim()
if ($branch -ne "packaging/windows-installer") {
    throw "Packaging is only allowed on packaging/windows-installer; current: $branch"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python not found: $Python"
}
$modelRootPath = (Resolve-Path -LiteralPath $ModelRoot).Path

function Reset-BuildDirectory([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $allowedParent = [IO.Path]::GetFullPath($projectRoot)
    if (-not $full.StartsWith($allowedParent + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing to reset path outside project: $full"
    }
    if (Test-Path -LiteralPath $full) {
        Remove-Item -LiteralPath $full -Recurse -Force
    }
    New-Item -ItemType Directory -Path $full -Force | Out-Null
}

$manifestPath = Join-Path $PSScriptRoot "model_manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
foreach ($item in $manifest) {
    $source = Join-Path $modelRootPath $item.source
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required model is missing: $source"
    }
    $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($actual -ne $item.sha256) {
        throw "Model SHA256 mismatch: $source"
    }
}

$workPath = Join-Path $projectRoot "build\pyinstaller"
$distRoot = Join-Path $projectRoot "dist"
$appDist = Join-Path $distRoot "HearU Mate"
Reset-BuildDirectory $workPath
if (Test-Path -LiteralPath $appDist) {
    $resolvedDist = [IO.Path]::GetFullPath($appDist)
    if (-not $resolvedDist.StartsWith([IO.Path]::GetFullPath($distRoot))) {
        throw "Unexpected dist path: $resolvedDist"
    }
    Remove-Item -LiteralPath $resolvedDist -Recurse -Force
}
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null

& $Python -m PyInstaller --noconfirm --clean `
    --distpath $distRoot `
    --workpath $workPath `
    (Join-Path $PSScriptRoot "hearu_mate.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$installedModels = Join-Path $appDist "models"
foreach ($item in $manifest) {
    $source = Join-Path $modelRootPath $item.source
    $destination = Join-Path $installedModels $item.destination
    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$buildInfo = [ordered]@{
    product = "HearU Mate"
    version = $Version
    built_at = (Get-Date).ToUniversalTime().ToString("o")
    branch = $branch
    commit = (& git -C $projectRoot rev-parse HEAD).Trim()
}
$buildInfo | ConvertTo-Json | Set-Content `
    -LiteralPath (Join-Path $appDist "BUILD_INFO.json") `
    -Encoding UTF8

$exe = Join-Path $appDist "HearU Mate.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Packaged executable is missing: $exe"
}
$check = Start-Process -FilePath $exe -ArgumentList "--self-check" `
    -WindowStyle Hidden -Wait -PassThru
if ($check.ExitCode -ne 0) {
    $selfCheckLog = Join-Path $appDist "self-check-error.log"
    if (Test-Path -LiteralPath $selfCheckLog -PathType Leaf) {
        Write-Host (Get-Content -LiteralPath $selfCheckLog -Raw)
    }
    throw "Packaged self-check failed with exit code $($check.ExitCode)"
}

if (-not $SkipInstaller) {
    $isccCandidates = @(
        (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
        (Join-Path $projectRoot "build\tools\Inno Setup 7\ISCC.exe"),
        "C:\Program Files\Inno Setup 7\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    if (-not $isccCandidates) {
        throw "Inno Setup compiler was not found. Install Inno Setup 7/6 or use -SkipInstaller."
    }
    $releaseDir = Join-Path $projectRoot "release"
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    & $isccCandidates[0] "/DMyAppVersion=$Version" `
        (Join-Path $PSScriptRoot "installer.iss")
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Build completed: $appDist"
