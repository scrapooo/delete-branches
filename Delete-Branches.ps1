<#
# 删除本地/远程分支的 PowerShell 入口。
# 实际逻辑由 delete_branches.py 实现。
#
# 删除记录会写入同目录下的 delete-branches.log（含时间戳、分支名、commit-id）。
#
# Usage:
#   .\Delete-Branches.ps1 [-Branches branch1,branch2] [-BranchesFile branches.txt] [-Remote origin] [-DryRun]
#   .\Delete-Branches.ps1              # 无参数 = 交互式多选
#>

Param(
    [Parameter(Mandatory=$false, Position=0, ValueFromPipeline=$true)]
    [string[]]$Branches,
    [string]$Remote = "origin",
    [switch]$DryRun,
    [string]$Separator = ',',
    [string]$BranchesFile
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyScript = Join-Path $scriptDir "delete_branches.py"

if (-not (Test-Path $pyScript)) {
    Write-Host "[错误] 未找到 Python 脚本: $pyScript" -ForegroundColor Red
    exit 1
}

$python = $null
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) { $python = "py" }
else {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) { $python = "python" }
    else {
        Write-Host "[错误] 未找到 Python。请安装 Python 并确保 python 或 py 在 PATH 中。" -ForegroundColor Red
        exit 1
    }
}

# Force UTF-8 for child Python process to avoid GBK decode errors from git output
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$pyArgs = @($pyScript)
if ($Branches) {
    $pyArgs += "--branches"
    $pyArgs += $Branches
}
if ($BranchesFile) { $pyArgs += @("--branches-file", $BranchesFile) }
if ($Remote -ne "origin") { $pyArgs += @("--remote", $Remote) }
if ($Separator -ne ",")   { $pyArgs += @("--separator", $Separator) }
if ($DryRun)              { $pyArgs += "--dry-run" }

& $python @pyArgs
exit $LASTEXITCODE
