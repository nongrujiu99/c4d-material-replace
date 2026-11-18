<#
.SYNOPSIS
    一键把「材质替换」脚本安装到本机所有已安装的 Cinema 4D 用户脚本目录。

.DESCRIPTION
    从 GitHub 克隆本仓库后，在仓库根目录运行本脚本即可。
    只做一件事：把 材质替换.py 复制到 %APPDATA%\Maxon\Maxon Cinema 4D *\library\scripts\。
    不联网、不下载、不提权、不写注册表、不修改 C4D 的任何设置。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
#>

$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot '材质替换.py'
if (-Not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "找不到 材质替换.py —— 请在仓库根目录运行本脚本。"
}

$appData = [Environment]::GetFolderPath('ApplicationData')
$maxonRoot = Join-Path $appData 'Maxon'

if (-Not (Test-Path -LiteralPath $maxonRoot -PathType Container)) {
    throw "没有找到 Maxon 配置目录：$maxonRoot`n请先至少启动一次 Cinema 4D，再运行本脚本。"
}

$allVersions = @(Get-ChildItem -LiteralPath $maxonRoot -Directory |
                 Where-Object { $_.Name -like 'Maxon Cinema 4D *' })

if ($allVersions.Count -eq 0) {
    throw "在 $maxonRoot 下没有找到任何 Cinema 4D 配置目录。"
}

# 只装 Python 3 的版本（R23 / S24 / 2023+）。R21 及更早是 Python 2.7，未验证，
# 默认跳过；确需要可设环境变量 C4D_INSTALL_ALL=1。
$versions = @()
foreach ($candidate in $allVersions) {
    $token = $candidate.Name -replace '^Maxon Cinema 4D\s*', ''
    $match = [regex]::Match($token, '\d+')
    $major = 0
    if ($match.Success) { $major = [int]$match.Value }

    if ($major -ge 23 -or $env:C4D_INSTALL_ALL -eq '1') {
        $versions += $candidate
    } else {
        Write-Host "  跳过：$($candidate.Name)（Python 2.7 未验证）"
    }
}

if ($versions.Count -eq 0) {
    throw "没有符合版本要求的 Cinema 4D（需要 R23 / S24 / 2023 及以上）。"
}

$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
$installed = @()

foreach ($version in $versions) {
    $scriptsDir = Join-Path $version.FullName 'library\scripts'
    if (-Not (Test-Path -LiteralPath $scriptsDir -PathType Container)) {
        New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
        Write-Host "  已创建目录：$scriptsDir"
    }

    $dest = Join-Path $scriptsDir '材质替换.py'

    if (Test-Path -LiteralPath $dest -PathType Leaf) {
        $oldHash = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
        if ($oldHash -eq $sourceHash) {
            Write-Host "  已是最新，跳过：$($version.Name)"
            $installed += $dest
            continue
        }
        $backup = "$dest.bak"
        Copy-Item -LiteralPath $dest -Destination $backup -Force
        Write-Host "  已备份旧文件：$backup"
    }

    Copy-Item -LiteralPath $source -Destination $dest -Force

    $newHash = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
    if ($newHash -ne $sourceHash) {
        throw "复制后校验失败：$dest"
    }
    Write-Host "  已安装：$dest"
    $installed += $dest
}

Write-Host ''
Write-Host "安装完成，共 $($installed.Count) 处：" -ForegroundColor Green
$installed | ForEach-Object { Write-Host "  $_" }
Write-Host ''
Write-Host "请重启 Cinema 4D，然后从菜单「脚本 → 材质替换」运行。" -ForegroundColor Green
