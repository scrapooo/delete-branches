<#
# 将本脚本所在目录添加到当前用户的 PATH 环境变量中。
# 新电脑 clone 项目后执行一次即可全局使用 Delete-Branches 命令。
#
# Usage:
#   .\install.ps1
#>

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $currentPath) { $currentPath = "" }

$paths = $currentPath -split ";" | Where-Object { $_ -ne "" }

$alreadyExists = $paths | Where-Object { $_.TrimEnd("\") -eq $scriptDir.TrimEnd("\") }
if ($alreadyExists) {
    Write-Host "[提示] 目录已在 PATH 中，无需重复添加：" -ForegroundColor Yellow
    Write-Host "  $scriptDir"
    exit 0
}

$newPath = ($paths + $scriptDir) -join ";"
[Environment]::SetEnvironmentVariable("Path", $newPath, "User")

Write-Host "[完成] 已将以下目录添加到用户 PATH：" -ForegroundColor Green
Write-Host "  $scriptDir"
Write-Host ""
Write-Host "请重新打开终端使 PATH 生效。" -ForegroundColor DarkGray
