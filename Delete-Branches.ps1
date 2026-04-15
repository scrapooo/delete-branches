<#
# Deletes local and remote branches.
#
# Usage:
#   .\Delete-Branches.ps1 -Branches branch1,branch2 [-Remote origin] [-DryRun]
#   .\Delete-Branches.ps1 -BranchesFile branches.txt [-Remote origin] [-DryRun]
#
# Notes about commas in branch names:
# - If a branch name itself contains a comma, wrap it in quotes so PowerShell treats it as a single string, for example:
#     .\Delete-Branches.ps1 -Branches 'bugfix/issue,42'
# - Or put branch names into a file (one per line) and use -BranchesFile to avoid delimiter issues.
# - You can change the splitting delimiter with -Separator (default is comma).
#
# Examples:
#   .\Delete-Branches.ps1 -Branches feature/a,feature/b
#   .\Delete-Branches.ps1 -Branches 'bugfix/issue,42' -Branches 'feature/x'
#   .\Delete-Branches.ps1 -BranchesFile .\\branches.txt
#   .\Delete-Branches.ps1 -Branches "a;b" -Separator ';'
#>

Param(
    [Parameter(Mandatory=$false, Position=0, ValueFromPipeline=$true)]
    [string[]]$Branches,
    [string]$Remote = "origin",
    [switch]$DryRun,
    [string]$Separator = ',',
    [string]$BranchesFile
)

# 构建最终要处理的分支列表，支持从文件读取或用自定义分隔符拆分
$branchesList = @()
if ($BranchesFile) {
    if (-not (Test-Path $BranchesFile)) {
        Write-Error "BranchesFile 未找到: $BranchesFile"
        exit 1
    }
    $fileLines = Get-Content $BranchesFile | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
    $branchesList += $fileLines
}
if ($Branches) {
    foreach ($b in $Branches) {
        if ($Separator -ne '' -and $b -like "*$Separator*") {
            $parts = $b -split [regex]::Escape($Separator)
            foreach ($p in $parts) { if ($p.Trim() -ne '') { $branchesList += $p.Trim() } }
        } else {
            $branchesList += $b
        }
    }
}

if ($branchesList.Count -eq 0) {
    Write-Error "没有提供任何分支。使用 -Branches 或 -BranchesFile 参数。"
    exit 1
}

foreach ($branch in $branchesList) {
    Write-Host "=== 处理分支: $branch ==="

    # 检查本地分支是否存在
    & git show-ref --verify --quiet "refs/heads/$branch" 2>$null
    $localExists = $LASTEXITCODE -eq 0
    if ($localExists) { Write-Host "本地分支存在：$branch" } else { Write-Host "本地分支不存在：$branch" }

    # 检查远程分支是否存在
    & git ls-remote --exit-code $Remote "refs/heads/$branch" >$null 2>$null
    $remoteExists = $LASTEXITCODE -eq 0
    if ($remoteExists) { Write-Host "远程分支存在：$Remote/$branch" } else { Write-Host "远程分支不存在：$branch" }

    if (-not $localExists -and -not $remoteExists) {
        Write-Host ""
        continue
    }

    if ($DryRun) {
        if ($localExists) { Write-Host "[dry-run] git branch -D $branch" }
        if ($remoteExists) { Write-Host "[dry-run] git push $Remote --delete $branch" }
        Write-Host ""
        continue
    }

    # 询问用户确认要删除的目标
    $targets = @()
    if ($localExists) { $targets += "本地:$branch" }
    if ($remoteExists) { $targets += "远程:$Remote/$branch" }
    $confirmMsg = "确认删除 " + ($targets -join ", ") + " ? (y/N)"
    $ans = Read-Host $confirmMsg
    if ($ans -notin @('y','Y','yes','YES','Yes')) {
        Write-Host "已跳过 $branch"
        Write-Host ""
        continue
    }

    if ($localExists) {
        & git branch -D $branch
        if ($LASTEXITCODE -eq 0) { Write-Host "已删除本地分支 $branch" } else { Write-Host "删除本地分支失败：$branch" }
    }
    if ($remoteExists) {
        & git push $Remote --delete $branch
        if ($LASTEXITCODE -eq 0) { Write-Host "已删除远程分支 $Remote/$branch" } else { Write-Host "删除远程分支失败：$Remote/$branch" }
    }

    Write-Host ""
}
