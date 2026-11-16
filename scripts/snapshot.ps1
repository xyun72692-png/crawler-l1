# snapshot.ps1 -- timestamped copy-backup of selected folders.
# DESIGN RULES (do not change):
#   * NEVER uses /MIR or /PURGE. Extra files in the destination are never deleted.
#   * /XJ skips reparse points (junctions / mount points).
#   * Every snapshot gets its own timestamped folder; old snapshots are kept.
#   * Produces manifest.csv + summary.json so a single file can be restored later.
#
# Exit codes: 0 = success, 1 = copy problems, 2 = verification mismatch.

param(
    [string[]]$Source = @('C:\Users\HUAWEI\Desktop'),
    [string]$DestinationRoot = 'D:\agent-work\archive',
    [string]$Label = 'snapshot',
    [string[]]$ExcludeDirs = @(),
    [int]$VerifySamples = 30,
    [switch]$FastHash
)

$ErrorActionPreference = 'Continue'

$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$dest   = Join-Path $DestinationRoot ("{0}-{1}" -f $Label, $stamp)
$logDir = 'D:\agent-work\logs'
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logPath = Join-Path $logDir ("snapshot-{0}-{1}.log" -f $Label, $stamp)

if (-not (Test-Path -LiteralPath $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }

Write-Host ("[snapshot] dest = {0}" -f $dest)

# ---------- helper: enumerate files without following reparse points ----------
function Get-FilesSafe {
    param([string]$Root)
    $stack = New-Object System.Collections.Stack
    $stack.Push($Root)
    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        try { $entries = [System.IO.Directory]::GetFileSystemEntries($dir) }
        catch { continue }
        foreach ($p in $entries) {
            $attr = [System.IO.File]::GetAttributes($p)
            if ($attr -band [System.IO.FileAttributes]::ReparsePoint) { continue }
            if ($attr -band [System.IO.FileAttributes]::Directory) { $stack.Push($p) }
            else { $p }
        }
    }
}

function Get-Md5 {
    param([string]$Path)
    try {
        $h = Get-FileHash -LiteralPath $Path -Algorithm MD5 -ErrorAction Stop
        return $h.Hash
    } catch { return '' }
}

# ---------- copy ----------
$robolog = Join-Path $logDir ("robocopy-{0}-{1}.log" -f $Label, $stamp)
$copyFail = $false
$srcInfo  = @()

foreach ($s in $Source) {
    if (-not (Test-Path -LiteralPath $s)) {
        Write-Warning ("[snapshot] source missing, skipped: {0}" -f $s)
        continue
    }
    $leaf = Split-Path -Path $s -Leaf
    $target = Join-Path $dest $leaf
    $roboArgs = @($s, $target, '/E', '/COPY:DAT', '/R:1', '/W:1', '/XJ', '/NFL', '/NDL', '/NP', '/NJH', '/NJS', ('/LOG+:{0}' -f $robolog))
    if ($ExcludeDirs.Count -gt 0) { $roboArgs += '/XD'; $roboArgs += $ExcludeDirs }
    & robocopy.exe @roboArgs | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { $copyFail = $true }
    Write-Host ("[snapshot] robocopy {0} -> {1}  rc={2}" -f $s, $target, $rc)
    $srcInfo += [pscustomobject]@{ Source = $s; Leaf = $leaf; Target = $target; RoboExit = $rc }
}

# ---------- manifest of the source ----------
# 注意：md5 必须从【源文件】算，不能从副本算。
# 早期版本从副本算，导致验证时"副本和自己比"恒等，hashMismatch 永远是 0。
# 这里用 $srcPaths 与 $rows 同下标，保证算的是源。
$rows = New-Object System.Collections.Generic.List[object]
$srcPaths = New-Object System.Collections.Generic.List[string]
foreach ($s in $Source) {
    if (-not (Test-Path -LiteralPath $s)) { continue }
    $leaf = Split-Path -Path $s -Leaf
    $base = (Resolve-Path -LiteralPath $s).Path
    foreach ($f in (Get-FilesSafe -Root $base)) {
        $rel = $f.Substring($base.Length).TrimStart('\')
        $len = 0; $lw = ''
        try {
            $fi = New-Object System.IO.FileInfo $f
            $len = $fi.Length
            $lw  = $fi.LastWriteTimeUtc.ToString('o')
        } catch { }
        $rows.Add([pscustomobject]@{
            leaf       = $leaf
            relpath    = $rel
            bytes      = $len
            lastwrite  = $lw
            md5        = ''
        })
        $srcPaths.Add($f)
    }
}

# ---------- hashing: full by default, sampled with -FastHash ----------
# 注意 $hashFailed 必须在 if 外面初始化：源为空时循环不执行，若变量未定义，
# ok 的计算会得到 $null -eq 0 = False，凭空报 PROBLEM。
$hashFailed = 0
if ($rows.Count -gt 0) {
    $idx = New-Object System.Collections.Generic.List[int]
    if ($FastHash) {
        $n = [Math]::Min($VerifySamples, $rows.Count)
        if ($n -eq 1) { $idx.Add(0) }
        elseif ($n -gt 1) {
            for ($k = 0; $k -lt $n; $k++) {
                $i = [int][Math]::Floor($k * ($rows.Count - 1) / ($n - 1))
                if (-not $idx.Contains($i)) { $idx.Add($i) }
            }
        }
    } else {
        for ($i = 0; $i -lt $rows.Count; $i++) { $idx.Add($i) }
    }
    foreach ($i in $idx) {
        # 从源文件算哈希（$srcPaths 与 $rows 同下标）
        # 算不出来（源被删/读不了）必须计入失败，不能让 ok 还是 true
        $h = Get-Md5 -Path $srcPaths[$i]
        if ([string]::IsNullOrWhiteSpace($h)) { $hashFailed++ }
        $rows[$i].md5 = $h
    }
}

# ---------- verification: every source file exists in destination with same length ----------
$missing = 0; $sizeMismatch = 0; $hashMismatch = 0
$totalBytes = 0
foreach ($r in $rows) {
    $totalBytes += $r.bytes
    $full = Join-Path (Join-Path $dest $r.leaf) $r.relpath
    if (-not (Test-Path -LiteralPath $full)) { $missing++; continue }
    try {
        $dl = (New-Object System.IO.FileInfo $full).Length
        if ($dl -ne $r.bytes) { $sizeMismatch++ }
    } catch { $sizeMismatch++ }
    if ($r.md5 -ne '') {
        $dh = Get-Md5 -Path $full
        if ($dh -ne $r.md5) { $hashMismatch++ }
    }
}

# ---------- write manifest & summary ----------
$manifest = Join-Path $dest 'manifest.csv'
$rows | Export-Csv -LiteralPath $manifest -NoTypeInformation -Encoding UTF8

$doneFiles = 0; $doneBytes = 0
foreach ($s in $Source) {
    if (-not (Test-Path -LiteralPath $s)) { continue }
    $leaf = Split-Path -Path $s -Leaf
    $t = Join-Path $dest $leaf
    if (Test-Path -LiteralPath $t) {
        $fl = Get-FilesSafe -Root $t
        $doneFiles += @($fl).Count
        foreach ($f in $fl) { try { $doneBytes += (New-Object System.IO.FileInfo $f).Length } catch { } }
    }
}

$summary = [ordered]@{
    stamp          = $stamp
    dest           = $dest
    sources        = @($Source)
    excludedDirs   = @($ExcludeDirs)
    srcFiles       = $rows.Count
    srcBytes       = $totalBytes
    destFiles      = $doneFiles
    destBytes      = $doneBytes
    hashedFiles    = @($rows | Where-Object { $_.md5 -ne '' }).Count
    hashFailed     = $hashFailed
    hashMode       = 'source-vs-copy'
    missing        = $missing
    sizeMismatch   = $sizeMismatch
    hashMismatch   = $hashMismatch
    robocopyLog    = $robolog
    verifyLog      = $logPath
    ok             = ($missing -eq 0 -and $sizeMismatch -eq 0 -and $hashMismatch -eq 0 -and $hashFailed -eq 0 -and -not $copyFail)
}
$summaryPath = Join-Path $dest 'summary.json'
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

$msg = @()
$msg += ("snapshot {0}" -f $stamp)
$msg += ("dest      : {0}" -f $dest)
$msg += ("srcFiles  : {0}  ({1:N1} MB)" -f $rows.Count, ($totalBytes / 1MB))
$msg += ("destFiles : {0}  ({1:N1} MB)" -f $doneFiles, ($doneBytes / 1MB))
$msg += ("hashedFiles: {0}/{1}  hashFailed={2}  missing={3} sizeMismatch={4} hashMismatch={5}" -f $summary.hashedFiles, $rows.Count, $hashFailed, $missing, $sizeMismatch, $hashMismatch)
$msg += ("robocopy issues: {0}" -f $copyFail)
$msg += ("RESULT: {0}" -f $(if ($summary.ok) { 'OK' } else { 'PROBLEM' }))
$msg | Set-Content -LiteralPath $logPath -Encoding UTF8
$msg | ForEach-Object { Write-Host $_ }

if (-not $summary.ok) { exit 2 }
if ($copyFail) { exit 1 }
exit 0