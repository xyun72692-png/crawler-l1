# documents-backup.ps1 -- Documents 的增量备份（不进每次桌面快照）
#
# 为什么不并进 snapshot.ps1：
#   Documents 有 22780 个文件 / 5.2 GB，而桌面只有 770 个 / 396 MB。
#   每次清桌面都全量拷 5.2 GB，会把"5 秒的操作"变成"一分钟以上"，还会让 archive 迅速膨胀。
#
# 所以分成两条线：
#   Desktop   -> snapshot.ps1       每次操作前，全量，5-8 秒，带完整 manifest 和哈希
#   Documents -> 本脚本            增量，只拷变化的文件，建议每周一次或手动触发
#
# 用法：
#   # 先看会拷什么（不写任何文件）
#   .\documents-backup.ps1 -Destination D:\Backup\Documents -DryRun
#
#   # 真拷（增量：已存在且没变的跳过）
#   .\documents-backup.ps1 -Destination D:\Backup\Documents
#
#   # 只备份某些子目录
#   .\documents-backup.ps1 -Destination D:\Backup\Documents -Include 'Codex','deepseek-harness'
#
# 退出码：0 成功 / 1 robocopy 报告问题 / 2 参数问题

param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$Source = 'C:\Users\HUAWEI\Documents',
    [string[]]$Include = @(),
    [switch]$DryRun,
    [string]$LogDir = 'D:\agent-work\logs'
)

$ErrorActionPreference = 'Continue'

if (-not (Test-Path -LiteralPath $Source)) { Write-Host "源目录不存在: $Source"; exit 2 }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$log = Join-Path $LogDir ("documents-backup-{0}.log" -f $stamp)

# 目标在源里面 = 会自己拷自己，直接拒绝
$srcFull = [System.IO.Path]::GetFullPath($Source).TrimEnd('\')
$dstFull = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
if ($dstFull.StartsWith($srcFull + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "拒绝：目标目录在源目录里面，会无限自我复制 -> $Destination"
    exit 2
}

Write-Host ('=' * 60)
Write-Host ("源    : {0}" -f $srcFull)
Write-Host ("目标  : {0}" -f $dstFull)
Write-Host ("模式  : {0}" -f $(if ($DryRun) { 'DRY-RUN（只列出，不写文件）' } else { '真实增量备份' }))
if ($Include.Count -gt 0) { Write-Host ("仅包含: {0}" -f ($Include -join ', ')) }
Write-Host ('=' * 60)

# 统计源规模（不含 junction，避免钻进 D 盘）
$files = New-Object System.Collections.Generic.List[object]
$stack = New-Object System.Collections.Stack
foreach ($d in (Get-ChildItem -LiteralPath $srcFull -Directory -Force -ErrorAction SilentlyContinue)) {
    if ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    if ($Include.Count -gt 0 -and ($Include -notcontains $d.Name)) { continue }
    $stack.Push($d.FullName)
}
while ($stack.Count -gt 0) {
    $dir = $stack.Pop()
    try { $entries = [System.IO.Directory]::GetFileSystemEntries($dir) } catch { continue }
    foreach ($p in $entries) {
        $attr = [System.IO.File]::GetAttributes($p)
        if ($attr -band [System.IO.FileAttributes]::ReparsePoint) { continue }
        if ($attr -band [System.IO.FileAttributes]::Directory) { $stack.Push($p) }
        else { $files.Add((New-Object System.IO.FileInfo $p)) }
    }
}
$totalMB = [math]::Round((($files | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host ("源规模: {0} 个文件 / {1} MB" -f $files.Count, $totalMB)

if (-not (Test-Path -LiteralPath $dstFull)) {
    if ($DryRun) { Write-Host '（DRY-RUN：目标目录还不存在，实际运行时会创建）' }
    else { New-Item -ItemType Directory -Path $dstFull -Force | Out-Null }
}

# robocopy 增量参数：
#   /E     含子目录（空目录也建）
#   /XO    排除"源比目标旧"的文件 —— 这是增量的关键，但不删目标多余文件
#   /XJ    跳过 junction
#   /R:1 /W:1  失败只重试 1 次、等 1 秒（不卡死）
#   绝不加 /MIR 或 /PURGE
$baseArgs = @('/E', '/XO', '/COPY:DAT', '/R:1', '/W:1', '/XJ',
              '/NFL', '/NDL', '/NP', '/NJH', ("/LOG+:{0}" -f $log))
if ($DryRun) { $baseArgs += '/L' }

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$rcs = @()

if ($Include.Count -gt 0) {
    # 指定了子目录：逐个单独 robocopy（不使用 /IF，那个参数接的是文件名模式，不是目录路径）
    foreach ($inc in $Include) {
        $sub = Join-Path $srcFull $inc
        if (-not (Test-Path -LiteralPath $sub)) { Write-Host ("跳过（不存在）: {0}" -f $inc); continue }
        $a = @($sub, (Join-Path $dstFull $inc)) + $baseArgs
        & robocopy.exe @a | Out-Null
        $rcs += $LASTEXITCODE
        Write-Host ("  {0} -> rc={1}" -f $inc, $LASTEXITCODE)
    }
} else {
    $a = @($srcFull, $dstFull) + $baseArgs
    & robocopy.exe @a | Out-Null
    $rcs += $LASTEXITCODE
}

$sw.Stop()
$rc = 0
if ($rcs.Count -gt 0) { $rc = ($rcs | Measure-Object -Maximum).Maximum }

# robocopy 退出码：0=无变化 1=有复制 2=有额外文件 3=1+2 ... >=8 才是失败
$ok = ($rc -lt 8)
Write-Host ''
Write-Host ("robocopy 退出码: {0}（0=无变化 1=已复制 2=目标有源没有的文件 3=两者都有）" -f $rc)
Write-Host ("耗时: {0:N1} 秒" -f $sw.Elapsed.TotalSeconds)
Write-Host ("日志: {0}" -f $log)

if ($DryRun) {
    Write-Host ''
    Write-Host 'DRY-RUN 结束，没有写入任何文件。去掉 -DryRun 才会真拷。'
}

if (-not $ok) { exit 1 }
exit 0