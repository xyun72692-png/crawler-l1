# verify-snapshot.ps1 -- 复核一个快照是否仍然有效
#
# 【判定模型】（核心，别改错）
#   manifest.csv 里的 md5 = 建快照那一刻源文件的哈希，它是唯一基准。
#
#   副本 MD5 != manifest     → 快照损坏        exit 1
#   副本缺失                 → 快照损坏        exit 1
#   快照里有 manifest 没记的文件 → 多余文件     默认报告，-Strict 时 exit 1
#   manifest 无哈希           → 无法验证        exit 3
#   源 MD5 != manifest        → 源在建快照后被改过（正常，只报告）
#   源文件不存在              → 快照保留了它（正常，只报告；-Strict 时 exit 1）
#
#   注意：不要退化成"源 vs 副本"比较 —— 那样会漏掉"源和副本被同时改成一样"
#   以及"manifest 本身写错"两种情况。
#
# 用法：
#   verify-snapshot.ps1 -SnapshotDir <snap>
#   verify-snapshot.ps1 -SnapshotDir <snap> -Sample 60
#   verify-snapshot.ps1 -SnapshotDir <snap> -Strict
#   verify-snapshot.ps1 -SnapshotDir <snap> -Quiet
#
# 退出码：
#   0 快照有效
#   1 快照损坏（副本损坏/副本缺失/多余文件(-Strict)/源缺失(-Strict)）
#   2 参数或文件问题
#   3 无法验证（manifest 里的条目都没有哈希）

param(
    [Parameter(Mandatory = $true)][string]$SnapshotDir,
    [string]$SourceRoot = 'C:\Users\HUAWEI',
    [int]$Sample = 0,
    [switch]$Strict,
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'

if (-not (Test-Path -LiteralPath $SnapshotDir)) { Write-Host "快照不存在: $SnapshotDir"; exit 2 }
$manifest = Join-Path $SnapshotDir 'manifest.csv'
if (-not (Test-Path -LiteralPath $manifest)) { Write-Host "找不到 manifest.csv: $manifest"; exit 2 }

$rows = Import-Csv -LiteralPath $manifest
if (-not $rows -or @($rows).Count -eq 0) { Write-Host 'manifest 是空的'; exit 2 }

$totalInManifest = @($rows).Count
$all = @($rows)
$isSampling = $false
if ($Sample -gt 0 -and $Sample -lt $all.Count) {
    $isSampling = $true
    $step = [Math]::Floor($all.Count / $Sample)
    if ($step -lt 1) { $step = 1 }
    $picked = @()
    for ($i = 0; $i -lt $all.Count -and $picked.Count -lt $Sample; $i += $step) { $picked += $all[$i] }
    $all = $picked
}

$checked       = 0
$copyCorrupt   = 0
$copyMissing   = 0
$noHash        = 0
$srcMissing    = 0
$srcChanged    = 0
$srcUnreadable = 0

$bad      = New-Object System.Collections.Generic.List[object]   # 导致 exit 1
$noHashL  = New-Object System.Collections.Generic.List[object]   # 导致 exit 3
$info     = New-Object System.Collections.Generic.List[object]   # 只报告

foreach ($r in $all) {
    $leaf = $r.leaf
    $rel  = $r.relpath
    $mh   = [string]$r.md5

    $src = Join-Path (Join-Path $SourceRoot $leaf) $rel
    $dst = Join-Path (Join-Path $SnapshotDir $leaf) $rel

    if ([string]::IsNullOrWhiteSpace($mh)) {
        $noHash++
        $noHashL.Add([pscustomobject]@{ type = 'no-manifest-hash'; file = "$leaf\$rel" })
        continue
    }

    if (-not (Test-Path -LiteralPath $dst)) {
        $copyMissing++
        $bad.Add([pscustomobject]@{ type = 'copy-missing'; file = "$leaf\$rel" })
        continue
    }

    try {
        $hDst = (Get-FileHash -LiteralPath $dst -Algorithm MD5).Hash
    } catch {
        $copyCorrupt++
        $bad.Add([pscustomobject]@{ type = 'copy-unreadable'; file = "$leaf\$rel" })
        continue
    }

    if ($hDst -ne $mh) {
        $copyCorrupt++
        $bad.Add([pscustomobject]@{
            type = 'copy-corrupt'; file = "$leaf\$rel"; manifest = $mh; copy = $hDst
        })
        continue
    }

    $checked++

    if (-not (Test-Path -LiteralPath $src)) {
        $srcMissing++
        $info.Add([pscustomobject]@{ type = 'source-missing'; file = "$leaf\$rel" })
        continue
    }
    try {
        $hSrc = (Get-FileHash -LiteralPath $src -Algorithm MD5).Hash
    } catch {
        $srcUnreadable++
        continue
    }
    if ($hSrc -ne $mh) {
        $srcChanged++
        $info.Add([pscustomobject]@{ type = 'source-changed'; file = "$leaf\$rel" })
    }
}

# ---------- 多余文件：快照里有、manifest 没记的 ----------
# 抽样模式下无法判断（只看了一部分），所以不做。
$extra = New-Object System.Collections.Generic.List[string]
if (-not $isSampling) {
    $known = @{}
    foreach ($r in $rows) {
        $known[(($r.leaf + '\' + $r.relpath).ToLower())] = $true
    }
    foreach ($leafDir in (Get-ChildItem -LiteralPath $SnapshotDir -Directory -ErrorAction SilentlyContinue)) {
        if ($leafDir.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        $stack = New-Object System.Collections.Stack
        $stack.Push($leafDir.FullName)
        while ($stack.Count -gt 0) {
            $dir = $stack.Pop()
            try { $entries = [System.IO.Directory]::GetFileSystemEntries($dir) } catch { continue }
            foreach ($p in $entries) {
                try { $attr = [System.IO.File]::GetAttributes($p) } catch { continue }
                if ($attr -band [IO.FileAttributes]::ReparsePoint) { continue }
                if ($attr -band [IO.FileAttributes]::Directory) { $stack.Push($p) }
                else {
                    $relInLeaf = $p.Substring($leafDir.FullName.Length).TrimStart('\')
                    $k = (($leafDir.Name + '\' + $relInLeaf).ToLower())
                    if (-not $known.ContainsKey($k)) { $extra.Add(($leafDir.Name + '\' + $relInLeaf)) }
                }
            }
        }
    }
}

# ---------- 输出 ----------
if (-not $Quiet) {
    Write-Host ('=' * 62)
    Write-Host ("快照        : {0}" -f $SnapshotDir)
    if ($isSampling) {
        Write-Host ("范围        : 抽检 {0} / 共 {1} 条 manifest 记录" -f $all.Count, $totalInManifest)
    } else {
        Write-Host ("范围        : 全量 {0} 条" -f $all.Count)
    }
    Write-Host ('-' * 62)
    Write-Host ("副本一致    : {0}" -f $checked)
    Write-Host ("副本损坏    : {0}   ← 快照失效" -f $copyCorrupt)
    Write-Host ("副本缺失    : {0}   ← 快照失效" -f $copyMissing)
    if (-not $isSampling) { Write-Host ("多余文件    : {0}   ← 快照里有、manifest 没记" -f $extra.Count) }
    Write-Host ("manifest无哈希: {0}   ← 无法验证" -f $noHash)
    Write-Host ('-' * 62)
    Write-Host ("源已变更    : {0}   （建快照后被改过，正常）" -f $srcChanged)
    Write-Host ("源已不存在  : {0}   （快照仍在保护这些文件）" -f $srcMissing)
    if ($srcUnreadable -gt 0) { Write-Host ("源读取失败  : {0}" -f $srcUnreadable) }
    Write-Host ('-' * 62)
}

$showList = {
    param($list, $max)
    $i = 0
    foreach ($item in $list) {
        if ($i -ge $max) { Write-Host ("  ... 还有 {0} 个" -f ($list.Count - $max)); break }
        $o = $item   # switch 会把 $_ 重绑成它的输入值，必须先存下来
        switch ($o.type) {
            'copy-corrupt' {
                Write-Host ("  [副本损坏] {0}" -f $o.file)
                Write-Host ("             manifest={0}" -f $o.manifest)
                Write-Host ("             副本    ={0}" -f $o.copy)
            }
            'no-manifest-hash' {
                Write-Host ("  [无哈希]   {0}（manifest 缺 md5，无法验证）" -f $o.file)
            }
            default {
                Write-Host ("  [{0}] {1}" -f $o.type, $o.file)
            }
        }
        $i++
    }
}

if ($bad.Count -gt 0) {
    Write-Host '快照有问题的条目：'
    & $showList $bad 20
    Write-Host ''
    Write-Host 'RESULT: 快照无效（副本与 manifest 不符或副本缺失）'
    exit 1
}

if (-not $isSampling -and $extra.Count -gt 0) {
    Write-Host '快照里有 manifest 没记录的文件：'
    $extra | Select-Object -First 20 | ForEach-Object { Write-Host ("  [多余] {0}" -f $_) }
    if ($extra.Count -gt 20) { Write-Host ("  ... 还有 {0} 个" -f ($extra.Count - 20)) }
    if ($Strict) {
        Write-Host ''
        Write-Host 'RESULT: 快照无效（-Strict：存在多余文件）'
        exit 1
    }
    Write-Host '  （默认只报告；加 -Strict 会因此判为无效）'
}

if ($noHash -gt 0) {
    if ($checked -eq 0) {
        Write-Host '快照无法验证：manifest 里的条目都没有哈希。'
        & $showList $noHashL 10
        Write-Host ''
        Write-Host 'RESULT: 无法验证（用旧版本 snapshot.ps1 生成的快照可能没有哈希，重跑一次即可）'
        exit 3
    }
    Write-Host ("注意：{0} 条 manifest 记录没有哈希，这些条目未验证。" -f $noHash)
}

if ($Strict -and ($srcMissing -gt 0 -or $srcChanged -gt 0)) {
    Write-Host ''
    Write-Host ("-Strict 模式下：源已变更 {0} 个、源已不存在 {1} 个 → 判为不一致" -f $srcChanged, $srcMissing)
    $info | Select-Object -First 20 | ForEach-Object {
        $o = $_
        Write-Host ("  [{0}] {1}" -f $o.type, $o.file)
    }
    exit 1
}

if (-not $Quiet) {
    Write-Host ''
    if ($isSampling) {
        Write-Host ("RESULT: 抽检通过（{0}/{1} 个副本与 manifest 一致；未抽检的 {2} 个未验证）" -f `
            $checked, $totalInManifest, ($totalInManifest - $all.Count))
    } else {
        Write-Host ("RESULT: 快照有效（{0} 个文件全部与 manifest 一致）" -f $checked)
    }
    if ($srcChanged -gt 0) { Write-Host ("        注意：{0} 个源文件在建快照后被修改过（快照保留的是旧版本）" -f $srcChanged) }
    if ($srcMissing -gt 0) { Write-Host ("        注意：{0} 个源文件已不存在（快照仍可作为恢复来源）" -f $srcMissing) }
}
exit 0