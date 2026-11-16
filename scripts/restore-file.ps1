# restore-file.ps1 -- restore one file (or one folder) from a snapshot.
# Verifies the stored MD5 against the restored copy when a hash is present.
#
# Usage examples:
#   restore-file.ps1 -SnapshotDir D:\agent-work\archive\snapshot-20261109-213000 -File 'Desktop\a.docx' -DryRun
#   restore-file.ps1 -SnapshotDir <snap> -File 'Desktop\subdir' -Force
#
# File paths are relative to -OriginalRoot and use the same layout as the snapshot:
#   <snapshot>\<topfolder>\<relative path>   ->   <OriginalRoot>\<topfolder>\<relative path>

param(
    [Parameter(Mandatory = $true)][string]$SnapshotDir,
    [Parameter(Mandatory = $true)][string]$File,
    [string]$OriginalRoot = 'C:\Users\HUAWEI',
    [switch]$Force,
    [switch]$DryRun,
    [switch]$AllowStale
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $SnapshotDir)) { Write-Host "snapshot not found: $SnapshotDir"; exit 2 }

# ---- 路径安全：规范化后必须仍在两个根目录之内 ----
# 不加这层，传 '..\..\Windows\System32\x.exe' 就能读写到快照和 OriginalRoot 之外。
$snapRoot = [System.IO.Path]::GetFullPath($SnapshotDir).TrimEnd('\')
$origRoot = [System.IO.Path]::GetFullPath($OriginalRoot).TrimEnd('\')

$rel = $File.TrimStart('\').TrimStart('/')
if ([string]::IsNullOrWhiteSpace($rel)) { Write-Host '拒绝：文件参数为空'; exit 2 }
if ($rel -match '^[A-Za-z]:') { Write-Host ("拒绝：不接受绝对路径 -> {0}" -f $File); exit 2 }

$from = [System.IO.Path]::GetFullPath((Join-Path $snapRoot $rel))
$to   = [System.IO.Path]::GetFullPath((Join-Path $origRoot $rel))

if (-not $from.StartsWith($snapRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Host ("拒绝：路径逃出快照目录 -> {0}" -f $File)
    Write-Host ("       解析结果 = {0}" -f $from)
    exit 2
}
if (-not $to.StartsWith($origRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Host ("拒绝：路径逃出目标根目录 -> {0}" -f $File)
    Write-Host ("       解析结果 = {0}" -f $to)
    exit 2
}

# ---- 再查一层：路径字符串合法，不代表物理位置合法 ----
# 如果目标路径的某一级上级目录是 junction / reparse point（比如 Desktop\sd-local 指向 D 盘），
# 字符串前缀检查会通过，但 Copy-Item 会顺着链接写到范围之外。
function Find-ReparseInPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    $cur = $full
    while ($cur -and $cur.Length -gt $root.Length) {
        if (Test-Path -LiteralPath $cur) {
            try {
                $attr = [System.IO.File]::GetAttributes($cur)
                if ($attr -band [System.IO.FileAttributes]::ReparsePoint) { return $cur }
            } catch { }
        }
        $cur = Split-Path -Path $cur -Parent
    }
    return $null
}

$parentOfTo = Split-Path -Path $to -Parent
$rp = Find-ReparseInPath -Path $parentOfTo
if ($rp) {
    Write-Host ("拒绝：目标路径的上级目录是 junction / reparse point")
    Write-Host ("       {0}" -f $rp)
    Write-Host '       写进去可能落到链接指向的位置（D 盘真实数据），超出校验范围。'
    exit 2
}
if ((Test-Path -LiteralPath $to)) {
    try {
        $toAttr = [System.IO.File]::GetAttributes($to)
        if ($toAttr -band [System.IO.FileAttributes]::ReparsePoint) {
            Write-Host ("拒绝：目标本身是 junction / reparse point -> {0}" -f $to)
            exit 2
        }
    } catch { }
}

if (-not (Test-Path -LiteralPath $from)) { Write-Host "not in snapshot: $rel"; exit 2 }

# If the manifest has no hash for this file, compute one now from the snapshot copy
# so the restored file can still be verified.
$fromIsDir = (Get-Item -LiteralPath $from).PSIsContainer

# $copyMd5     = 快照副本【现在的】哈希（B）
# $manifestMd5 = 建快照那一刻源文件的哈希（A）
# $verifyAgainst = 复制到目标之后，拿什么去比对。默认比"副本当前内容"。
#   正常情况 A 应等于 B；若不等就是 STALE。
#   【旧版的 bug】STALE 且 -AllowStale 时把 $expectMd5 覆盖成 A，
#   于是复制过去的 B 永远对不上 A，先写后失败、退出码 1、目标已被覆盖。
$copyMd5 = ''
if (-not $fromIsDir) {
    $copyMd5 = (Get-FileHash -LiteralPath $from -Algorithm MD5).Hash
}
$manifestMd5 = ''
$manifestPath = Join-Path $SnapshotDir 'manifest.csv'
if (Test-Path -LiteralPath $manifestPath) {
    $parts = $rel.Split('\')
    if ($parts.Count -ge 2) {
        $leaf  = $parts[0]
        $inner = ($parts[1..($parts.Count - 1)]) -join '\'
        $hit = Import-Csv -LiteralPath $manifestPath | Where-Object { $_.leaf -eq $leaf -and $_.relpath -eq $inner } | Select-Object -First 1
        if ($hit -ne $null) { $manifestMd5 = $hit.md5 }
    }
}
# 复制后校验的基准：默认是"副本当前内容"
$verifyAgainst = $copyMd5
$staleUsed = $false

if ($manifestMd5 -ne '' -and -not $fromIsDir) {
    if ($manifestMd5 -ne $copyMd5) {
        Write-Host ("STALE SNAPSHOT: manifest md5={0} but snapshot copy md5={1}" -f $manifestMd5, $copyMd5)
        Write-Host '  这份副本在建快照之后被改动过，它已经不是当初备份的那份内容。'
        if (-not $AllowStale) {
            Write-Host '  已中止：目标文件没有被动过。确认就要用这份过期副本，才加 -AllowStale。'
            exit 2
        }
        $staleUsed = $true
        Write-Host '  -AllowStale 已指定：会写入，但校验基准是【副本当前内容】，不是 manifest。'
        $verifyAgainst = $copyMd5
    } else {
        # 正常：A == B，用哪个都等价
        $verifyAgainst = $manifestMd5
    }
}

Write-Host ("from : {0}" -f $from)
Write-Host ("to   : {0}" -f $to)
if ($staleUsed) {
    Write-Host ("md5  : {0}   ← 过期副本（与 manifest {1} 不同）" -f $verifyAgainst, $manifestMd5)
} elseif ($verifyAgainst -ne '') {
    Write-Host ("md5  : {0}" -f $verifyAgainst)
}

if ($DryRun) { Write-Host 'DRY-RUN: nothing written'; exit 0 }

$parent = Split-Path -Path $to -Parent
if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

if (Test-Path -LiteralPath $to) {
    if (-not $Force) {
        Write-Host 'EXISTS: target already present, re-run with -Force to overwrite'
        exit 3
    }
}

$item = Get-Item -LiteralPath $from
if ($item.PSIsContainer) {
    & robocopy.exe $from $to /E /COPY:DAT /R:1 /W:1 /XJ /NFL /NDL /NP | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { Write-Host "restore failed rc=$rc"; exit 1 }
    Write-Host "RESTORED-FOLDER rc=$rc"
    exit 0
} else {
    Copy-Item -LiteralPath $from -Destination $to -Force
}

if ($verifyAgainst -ne '') {
    $got = (Get-FileHash -LiteralPath $to -Algorithm MD5).Hash
    if ($got -ne $verifyAgainst) {
        Write-Host ("MD5 MISMATCH got={0} expected={1}" -f $got, $verifyAgainst)
        Write-Host '  复制后的内容和快照副本对不上 —— 复制过程出错（磁盘/占用/权限）。'
        exit 1
    }
    if ($staleUsed) {
        Write-Host ("RESTORED-STALE md5={0}" -f $got)
        Write-Host '  注意：恢复的是【过期副本】的内容，不是建快照时的那一份。'
    } else {
        Write-Host ("RESTORED-OK md5={0}" -f $got)
    }
} else {
    Write-Host 'RESTORED (no hash recorded for this file)'
}
exit 0