# install.ps1 -- 软件安装助手（第 6 步产物）
#
# 一条命令走完"找 -> 看 -> 下 -> 验 -> 装 -> 记账"。
# 默认所有会改变系统的动作都是 dry-run，加 -Execute 才真干。
#
# 用法：
#   .\install.ps1 search  vscode                     搜包
#   .\install.ps1 show    Microsoft.VisualStudioCode 看发布者/版本（防山寨）
#   .\install.ps1 install Microsoft.VisualStudioCode 安装（默认只演练）
#   .\install.ps1 install Microsoft.VisualStudioCode -Execute
#   .\install.ps1 fetch   https://example.com/app.exe   下载+查签名+算哈希（不安装）
#   .\install.ps1 verify  D:\downloads\app.exe          只查签名和哈希
#   .\install.ps1 run     D:\downloads\app.exe -ArgList '/S'      演练安装命令
#   .\install.ps1 run     D:\downloads\app.exe -ArgList '/S' -Execute
#   .\install.ps1 log     -LogLimit 20                  看最近 20 条记账
#   .\install.ps1 uninstall-info 微信                    查卸载命令
#
# 退出码：0 成功 / 1 参数或环境问题 / 2 签名不合格 / 3 下载失败 / 4 安装失败

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('search', 'show', 'install', 'fetch', 'verify', 'run', 'log', 'uninstall-info')]
    [string]$Action,

    [Parameter(Position = 1)]
    [string]$Target,

    [string]$OutDir  = 'D:\agent-work\installers',
    [string]$LogPath = 'D:\agent-work\manifests\install-log.csv',

    [string[]]$ArgList = @(),
    [switch]$Silent,
    [switch]$Execute,
    [switch]$AllowUnsigned,
    [switch]$SkipSnapshot,
    [int]$LogLimit = 10
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36'

# =====================================================================
# 记账
# =====================================================================
function Add-LogRow {
    param([hashtable]$Row)

    $fields = @('timestamp', 'action', 'app_name', 'version', 'source_url',
                'sha256', 'sig_status', 'signer', 'args', 'exit_code',
                'uninstall_cmd', 'note')
    $vals = @()
    foreach ($f in $fields) {
        $v = ''
        if ($Row.ContainsKey($f)) { $v = [string]$Row[$f] }
        $v = ($v -replace "`r", ' ' -replace "`n", ' ').Trim()
        if ($v -match '[",]') { $v = '"' + $v.Replace('"', '""') + '"' }
        $vals += $v
    }

    $dir = Split-Path -Path $LogPath -Parent
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $LogPath)) {
        $hdr = ($fields -join ',') + "`r`n"
        [System.IO.File]::WriteAllText($LogPath, $hdr, (New-Object System.Text.UTF8Encoding($true)))
    }
    $line = ($vals -join ',') + "`r`n"
    [System.IO.File]::AppendAllText($LogPath, $line, (New-Object System.Text.UTF8Encoding($false)))
}

# =====================================================================
# 签名 / 哈希
# =====================================================================
function Test-Signature {
    param([string]$Path)

    $sig = Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction SilentlyContinue
    if ($null -eq $sig) {
        return [pscustomobject]@{ Status = 'Unknown'; Signer = ''; Note = '读取签名失败' }
    }
    $signer = ''
    if ($sig.SignerCertificate) {
        $signer = $sig.SignerCertificate.Subject
        # 只保留 CN= 之后的公司名，太长的主题串没意义
        $m = [regex]::Match($signer, 'CN=([^,]+)')
        if ($m.Success) { $signer = $m.Groups[1].Value.Trim() }
    }
    $note = ''
    switch ([string]$sig.Status) {
        'Valid'       { $note = '签名有效' }
        'NotSigned'   { $note = '没有数字签名（无法确认发布者）' }
        'HashMismatch'{ $note = '签名与文件内容不符（文件可能被改过）' }
        'NotTrusted'  { $note = '签名证书不受信任' }
        'UnknownError'{
            $ext = [System.IO.Path]::GetExtension($Path).ToLower()
            if (@('.exe', '.msi', '.dll', '.sys', '.cab', '.ps1', '.bat', '.cmd') -notcontains $ext) {
                $note = '不是可执行文件，没有签名概念'
            } else {
                $note = '签名校验出错（文件可能损坏或被截断）'
            }
        }
        default       { $note = [string]$sig.Status }
    }
    [pscustomobject]@{ Status = [string]$sig.Status; Signer = $signer; Note = $note }
}

function Show-FileFacts {
    param([string]$Path)

    $fi = Get-Item -LiteralPath $Path
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    $sig = Test-Signature -Path $Path

    Write-Host ''
    Write-Host '--- 文件信息 ---'
    Write-Host ("路径    : {0}" -f $fi.FullName)
    Write-Host ("大小    : {0:N2} MB" -f ($fi.Length / 1MB))
    Write-Host ("修改    : {0}" -f $fi.LastWriteTime)
    Write-Host ("SHA256  : {0}" -f $hash)
    Write-Host ("签名    : {0}  ({1})" -f $sig.Status, $sig.Note)
    Write-Host ("签名者  : {0}" -f $(if ($sig.Signer) { $sig.Signer } else { '(无)' }))

    return [pscustomobject]@{
        Path = $fi.FullName
        Bytes = $fi.Length
        Sha256 = $hash
        SigStatus = $sig.Status
        Signer = $sig.Signer
        SigNote = $sig.Note
    }
}

# =====================================================================
# winget 信息读取
# =====================================================================
function Get-WingetInfo {
    param([string]$Id)

    $raw = & winget show --id $Id -e --accept-source-agreements --disable-interactivity 2>&1
    $code = $LASTEXITCODE
    $text = ($raw | Out-String)

    $ver = ''
    $pub = ''
    $m = [regex]::Match($text, '(?m)^\s*(?:Version|版本)\s*[:：]\s*(.+?)\s*$')
    if ($m.Success) { $ver = $m.Groups[1].Value.Trim() }
    $m2 = [regex]::Match($text, '(?m)^\s*(?:Publisher|发布者)\s*[:：]\s*(.+?)\s*$')
    if ($m2.Success) { $pub = $m2.Groups[1].Value.Trim() }

    [pscustomobject]@{ ExitCode = $code; Text = $text; Version = $ver; Publisher = $pub }
}

function Get-InstalledVersion {
    param([string]$Id)

    $raw = & winget list --id $Id -e --accept-source-agreements --disable-interactivity 2>&1
    $text = ($raw | Out-String)

    # 不再"取最后一行"，改为找含包 ID 的那一行，再用正则抓版本号。
    # 中文界面 / 警告行 / 表头分隔线都不会再干扰。
    $line = ($text -split "`r?`n") |
            Where-Object { $_ -match [regex]::Escape($Id) } |
            Select-Object -First 1
    if (-not $line) { return '' }

    $m = [regex]::Match($line, '\s(\d+(?:\.\d+)+[0-9A-Za-z.\-]*)\s')
    if ($m.Success) { return $m.Groups[1].Value.Trim() }

    # 退一步：按两空格以上切列，取看起来像版本号的那一列
    $cells = ($line -replace '\s{2,}', '|') -split '\|'
    foreach ($c in $cells) {
        if ($c -match '^\d+(\.\d+)+') { return $c.Trim() }
    }
    return ''
}

function Get-InstalledPrograms {
    # 读注册表里所有"已安装程序"条目，用于安装前后对比
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName } |
        Select-Object DisplayName, DisplayVersion, UninstallString, QuietUninstallString
}

function Compare-InstalledPrograms {
    # 返回安装后新增的程序条目
    param($Before, $After)
    $beforeNames = @($Before | ForEach-Object { $_.DisplayName })
    $After | Where-Object { $beforeNames -notcontains $_.DisplayName }
}

function Add-ElevationAudit {
    <#
    提权审计：每一次拿到管理员权限都要留痕。
    为什么不用 CSV：参数里可能有逗号引号，JSONL 不用转义，一行一条也好读。
    #>
    param([string]$Exe, [string[]]$Args, [string]$Reason, [int]$ExitCode)

    $path = 'D:\agent-work\manifests\elevation-log.jsonl'
    $dir = Split-Path -Path $path -Parent
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    $rec = [ordered]@{
        timestamp = (Get-Date -Format 'o')
        user      = "$env:USERDOMAIN\$env:USERNAME"
        exe       = $Exe
        args      = @($Args)
        reason    = $Reason
        exit_code = $ExitCode
    }
    $line = ($rec | ConvertTo-Json -Compress -Depth 5) + "`r`n"
    [System.IO.File]::AppendAllText($path, $line, (New-Object System.Text.UTF8Encoding($false)))
}

function Invoke-InstallerElevated {
    <#
    用管理员权限跑安装器，并拿回真实退出码。

    【安全设计】参数一律走 JSON 文件，不拼进脚本字符串。
    早期版本把 $Exe 直接塞进 "Start-Process -FilePath '$Exe'"，
    路径里只要有一个单引号就能跳出字符串，在管理员上下文里执行任意命令。
    现在脚本里只硬编码一个 GUID 生成的路径，用户输入全部从 JSON 读。

    本机 ConsentPromptBehaviorAdmin=0，RunAs 静默，不会弹框 —— 所以审计日志是唯一痕迹。
    #>
    param([string]$Exe, [string[]]$ArgList, [string]$Reason = '')

    $tag = [guid]::NewGuid().ToString('N')
    $rcFile   = Join-Path $env:TEMP ("inst-rc-$tag.txt")
    $errFile  = Join-Path $env:TEMP ("inst-err-$tag.txt")
    $specFile = Join-Path $env:TEMP ("inst-spec-$tag.json")
    $shFile   = Join-Path $env:TEMP ("inst-$tag.ps1")

    if ([string]::IsNullOrWhiteSpace($Reason)) { $Reason = 'unspecified' }

    # 参数通过 JSON 传递
    $spec = [ordered]@{
        exe     = $Exe
        args    = @($ArgList)
        rcFile  = $rcFile
        errFile = $errFile
    }
    $spec | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $specFile -Encoding UTF8

    # 脚本正文只含 GUID 路径，不含任何用户输入
    $body = @"
`$ErrorActionPreference = 'Stop'
try {
    `$s = Get-Content -LiteralPath '$specFile' -Raw -Encoding UTF8 | ConvertFrom-Json
    `$p = Start-Process -FilePath `$s.exe -ArgumentList `$s.args -Wait -PassThru
    `$code = `$p.ExitCode
} catch {
    `$code = -99
    try { `$_.Exception.Message | Set-Content -LiteralPath `$s.errFile -Encoding UTF8 } catch { }
}
Set-Content -LiteralPath '$rcFile' -Value `$code -Encoding ASCII
"@
    Set-Content -LiteralPath $shFile -Value $body -Encoding UTF8

    Start-Process powershell.exe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $shFile) -Verb RunAs -Wait | Out-Null
    Start-Sleep -Milliseconds 500

    $rc = -1
    if (Test-Path -LiteralPath $rcFile) {
        try { $rc = [int]((Get-Content -LiteralPath $rcFile -Raw).Trim()) } catch { $rc = -1 }
    }
    if (Test-Path -LiteralPath $errFile) {
        $msg = Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue
        if ($msg) { Write-Host ("  提权执行异常: {0}" -f $msg.Trim()) }
    }
    Remove-Item -LiteralPath $rcFile, $shFile, $specFile, $errFile -Force -ErrorAction SilentlyContinue

    Add-ElevationAudit -Exe $Exe -Args $ArgList -Reason $Reason -ExitCode $rc
    return $rc
}

# =====================================================================
# 下载
# =====================================================================
function Download-Package {
    param([string]$Url)

    # 只允许 https：http 下载的安装包在传输途中可以被替换，签名是最后一道防线，不该先用裸 http 赌一把
    if ($Url -notmatch '^https://') {
        Write-Host ("拒绝：只接受 https:// 链接，收到的是 {0}" -f $Url)
        return $null
    }

    if (-not (Test-Path -LiteralPath $OutDir)) {
        New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    }

    $uri = [uri]$Url
    $name = [System.IO.Path]::GetFileName($uri.AbsolutePath)
    if ([string]::IsNullOrWhiteSpace($name)) { $name = 'download.bin' }
    $dest = Join-Path $OutDir $name

    if (Test-Path -LiteralPath $dest) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $name = "{0}.{1}{2}" -f [System.IO.Path]::GetFileNameWithoutExtension($name), $stamp, [System.IO.Path]::GetExtension($name)
        $dest = Join-Path $OutDir $name
        Write-Host ("同名文件已存在，改名保存为: {0}" -f $name)
    }

    Write-Host ("下载 {0}" -f $Url)
    Write-Host ("  ->  {0}" -f $dest)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        Invoke-WebRequest -Uri $Url -OutFile $dest -UseBasicParsing -UserAgent $UA -MaximumRedirection 10 -ErrorAction Stop
    } catch {
        Write-Host ("下载失败: {0}" -f $_.Exception.Message)
        return $null
    }
    $sw.Stop()

    # 记录最终落地 URL（经过重定向之后），用于事后判断"到底从哪下的"
    $finalUrl = $Url
    try {
        $head = Invoke-WebRequest -Uri $Url -Method Head -UseBasicParsing -UserAgent $UA -MaximumRedirection 10 -ErrorAction Stop
        if ($head.BaseResponse -and $head.BaseResponse.RequestMessage -and $head.BaseResponse.RequestMessage.RequestUri) {
            $finalUrl = $head.BaseResponse.RequestMessage.RequestUri.AbsoluteUri
        }
    } catch { }

    $mb = (Get-Item -LiteralPath $dest).Length / 1MB
    Write-Host ("完成: {0:N2} MB，用时 {1:N1} 秒" -f $mb, $sw.Elapsed.TotalSeconds)
    if ($finalUrl -ne $Url) { Write-Host ("重定向到: {0}" -f $finalUrl) }

    return [pscustomobject]@{
        Path      = $dest
        FinalUrl  = $finalUrl
        Bytes     = (Get-Item -LiteralPath $dest).Length
        Seconds   = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    }
}

# =====================================================================
# 主流程
# =====================================================================
Write-Host ('=' * 64)

switch ($Action) {

    'search' {
        if (-not $Target) { Write-Host '用法: install.ps1 search <关键词>'; exit 1 }
        Write-Host ("搜索: {0}" -f $Target)
        & winget search $Target --accept-source-agreements --disable-interactivity
        exit 0
    }

    'show' {
        if (-not $Target) { Write-Host '用法: install.ps1 show <包ID>'; exit 1 }
        $info = Get-WingetInfo -Id $Target
        Write-Host $info.Text
        Write-Host ''
        Write-Host '--- 关键字段 ---'
        Write-Host ("包ID    : {0}" -f $Target)
        Write-Host ("版本    : {0}" -f $(if ($info.Version) { $info.Version } else { '(未解析到)' }))
        Write-Host ("发布者  : {0}" -f $(if ($info.Publisher) { $info.Publisher } else { '(未解析到)' }))
        Write-Host ''
        Write-Host '> 看"发布者"是不是你要的那个公司。对不上就别装。'
        exit 0
    }

    'install' {
        if (-not $Target) { Write-Host '用法: install.ps1 install <包ID> [-Execute]'; exit 1 }

        $info = Get-WingetInfo -Id $Target
        if ($info.ExitCode -ne 0) {
            Write-Host ("winget 找不到这个包（退出码 {0}）。先跑 search 确认包ID。" -f $info.ExitCode)
            exit 1
        }

        $cur = Get-InstalledVersion -Id $Target
        Write-Host ("包ID    : {0}" -f $Target)
        Write-Host ("版本    : {0}" -f $info.Version)
        Write-Host ("发布者  : {0}" -f $info.Publisher)
        Write-Host ("已安装  : {0}" -f $(if ($cur) { $cur } else { '未安装' }))

        $wgArgs = @('install', '--id', $Target, '-e',
                    '--accept-package-agreements', '--accept-source-agreements',
                    '--disable-interactivity')
        if ($Silent) { $wgArgs += '--silent' }

        Write-Host ''
        Write-Host ("将执行: winget {0}" -f ($wgArgs -join ' '))

        if (-not $Execute) {
            Write-Host ''
            Write-Host 'DRY-RUN：没有真的安装。确认无误后加 -Execute。'
            Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'winget-install-dryrun'
                          app_name = $Target; version = $info.Version
                          sig_status = 'n/a'; args = ($wgArgs -join ' '); exit_code = 'dryrun'
                          note = ('publisher=' + $info.Publisher) }
            exit 0
        }

        # ---- 装前快照（默认做，-SkipSnapshot 跳过）----
        # 快照失败必须中止：安全网 fail-open 比没有安全网更危险
        if (-not $SkipSnapshot) {
            $snapScript = Join-Path $PSScriptRoot 'snapshot.ps1'
            if (Test-Path -LiteralPath $snapScript) {
                Write-Host ''
                Write-Host '装前快照中（-SkipSnapshot 可跳过）...'
                $snapOut = & pwsh -NoProfile -ExecutionPolicy Bypass -File $snapScript -Label ('preinstall-' + (Get-Date -Format 'HHmmss')) 2>&1
                $snapRc = $LASTEXITCODE
                $snapOut | Select-Object -Last 4 | Write-Host
                if ($snapRc -ne 0) {
                    Write-Host ''
                    Write-Host ("!! 装前快照失败（退出码 {0}）→ 中止安装。" -f $snapRc)
                    Write-Host '   你可能以为已经有保护了，实际没有。'
                    Write-Host '   先修好快照（看 D:\agent-work\logs\snapshot-*.log），'
                    Write-Host '   确实不需要快照才加 -SkipSnapshot 重跑。'
                    Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'abort-no-snapshot'
                                  app_name = $Target; exit_code = $snapRc
                                  note = 'pre-install snapshot failed, install aborted' }
                    exit 6
                }
                Write-Host '装前快照完成'
            } else {
                Write-Host '（找不到 snapshot.ps1）'
                if (-not $SkipSnapshot) {
                    Write-Host '!! 没有快照脚本 → 中止（要跳过快照请显式加 -SkipSnapshot）'
                    exit 6
                }
            }
        }

        $beforePrograms = Get-InstalledPrograms
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        & winget @wgArgs
        $rc = $LASTEXITCODE
        $sw.Stop()

        # ---- 装后验证：版本是否真的变了 ----
        $after = Get-InstalledVersion -Id $Target
        $afterPrograms = Get-InstalledPrograms
        $newOnes = @(Compare-InstalledPrograms -Before $beforePrograms -After $afterPrograms)

        Write-Host ''
        Write-Host ("退出码  : {0}   耗时 {1:N1} 秒" -f $rc, $sw.Elapsed.TotalSeconds)
        Write-Host ("装前版本: {0}" -f $(if ($cur) { $cur } else { '(未安装)' }))
        Write-Host ("装后版本: {0}" -f $(if ($after) { $after } else { '(未查到)' }))

        $verified = $false
        if ($cur -and $after -and $cur -ne $after) { $verified = $true }
        elseif (-not $cur -and $after) { $verified = $true }
        if ($newOnes.Count -gt 0) { $verified = $true }

        if ($verified) {
            Write-Host '装后验证: 通过（版本变化或注册表新增）'
        } else {
            Write-Host '装后验证: 未通过 —— 版本没变、注册表也没新增，这次安装可能没生效。'
            Write-Host '          请手动确认（或看 360 是否拦截了安装器）。'
        }
        if ($newOnes.Count -gt 0) {
            $newOnes | ForEach-Object { Write-Host ("  + {0}  ({1})" -f $_.DisplayName, $_.DisplayVersion) }
        }

        $uninst = ''
        if ($newOnes.Count -gt 0) {
            $f = $newOnes[0]
            if ($f.QuietUninstallString) { $uninst = $f.QuietUninstallString }
            elseif ($f.UninstallString) { $uninst = $f.UninstallString }
        }

        Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'winget-install'
                      app_name = $Target; version = $after
                      source_url = 'winget'
                      sig_status = 'winget-verified'; signer = $info.Publisher
                      args = ($wgArgs -join ' '); exit_code = $rc
                      uninstall_cmd = $uninst
                      note = ('requested=' + $info.Version + '; before=' + $cur + '; verified=' + $verified) }

        if ($rc -ne 0) { exit 4 }
        if (-not $verified) { exit 5 }
        exit 0
    }

    'fetch' {
        if (-not $Target) { Write-Host '用法: install.ps1 fetch <URL> [-Execute]'; exit 1 }

        if ($Target -notmatch '^https://') {
            Write-Host ("拒绝：只接受 https:// 链接，收到的是 {0}" -f $Target)
            exit 1
        }

        if (-not (Test-Path -LiteralPath $OutDir)) {
            New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
        }
        $guess = [System.IO.Path]::GetFileName(([uri]$Target).AbsolutePath)
        if ([string]::IsNullOrWhiteSpace($guess)) { $guess = 'download.bin' }

        Write-Host ("来源 URL : {0}" -f $Target)
        Write-Host ("保存到   : {0}" -f (Join-Path $OutDir $guess))

        if (-not $Execute) {
            Write-Host ''
            Write-Host 'DRY-RUN：没有下载。确认无误后加 -Execute。'
            Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'fetch-dryrun'
                          app_name = $guess; source_url = $Target
                          sig_status = 'pending'; exit_code = 'dryrun' }
            exit 0
        }

        $dl = Download-Package -Url $Target
        if ($null -eq $dl) { exit 3 }

        $facts = Show-FileFacts -Path $dl.Path
        $rc = 0
        if ($facts.SigStatus -ne 'Valid' -and -not $AllowUnsigned) { $rc = 2 }
        Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'download'
                      app_name = [System.IO.Path]::GetFileName($dl.Path)
                      version = ''
                      source_url = $dl.FinalUrl
                      sha256 = $facts.Sha256
                      sig_status = $facts.SigStatus
                      signer = $facts.Signer
                      exit_code = $rc
                      note = ($facts.SigNote + ' | ' + [math]::Round($dl.Bytes / 1MB, 2) + 'MB') }

        if ($rc -ne 0) {
            Write-Host ''
            Write-Host '!! 签名不是 Valid，不建议安装这个文件。'
            Write-Host '   如果确认来源可靠，可以加 -AllowUnsigned 继续，风险自负。'
            exit 2
        }
        Write-Host ''
        Write-Host '文件已下载并记录。下一步用 run 演练安装命令。'
        exit 0
    }

    'verify' {
        if (-not $Target) { Write-Host '用法: install.ps1 verify <文件路径>'; exit 1 }
        if (-not (Test-Path -LiteralPath $Target)) { Write-Host "文件不存在: $Target"; exit 1 }
        $facts = Show-FileFacts -Path $Target
        $rc = 0
        if ($facts.SigStatus -ne 'Valid') { $rc = 2 }
        Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'verify'
                      app_name = [System.IO.Path]::GetFileName($facts.Path)
                      source_url = $facts.Path
                      sha256 = $facts.Sha256
                      sig_status = $facts.SigStatus
                      signer = $facts.Signer
                      exit_code = $rc
                      note = $facts.SigNote }
        if ($rc -ne 0) { exit 2 }
        exit 0
    }

    'run' {
        if (-not $Target) { Write-Host '用法: install.ps1 run <安装包路径> [-ArgList "参数"] [-Execute]'; exit 1 }
        if (-not (Test-Path -LiteralPath $Target)) { Write-Host "文件不存在: $Target"; exit 1 }

        $facts = Show-FileFacts -Path $Target

        if ($facts.SigStatus -ne 'Valid' -and -not $AllowUnsigned) {
            Write-Host ''
            Write-Host '!! 签名不是 Valid，拒绝执行安装。'
            Write-Host '   确认来源可靠才加 -AllowUnsigned（风险自负）。'
            exit 2
        }

        # ---- 按扩展名决定怎么执行 ----
        $ext = [System.IO.Path]::GetExtension($facts.Path).ToLower()
        $isMsix = @('.msix', '.appx', '.msixbundle', '.appxbundle') -contains $ext
        $isMsi = ($ext -eq '.msi')
        $msiArgs = @()

        if ($isMsix) {
            $execDesc = 'Add-AppxPackage -Path "' + $facts.Path + '"'
        } elseif ($isMsi) {
            $msiArgs = @('/i', ('"{0}"' -f $facts.Path)) + $ArgList
            $execDesc = 'msiexec.exe ' + ($msiArgs -join ' ')
        } else {
            $execDesc = '"' + $facts.Path + '" ' + ($ArgList -join ' ')
        }

        Write-Host ''
        Write-Host ("将执行: {0}" -f $execDesc)

        if ($isMsi -and (($ArgList -join ' ') -notmatch '/q')) {
            Write-Host '提示: MSI 一般要带 /qn（完全静默）或 /qb（显示进度条），否则会弹出交互界面。'
        }

        if (-not $Execute) {
            Write-Host ''
            Write-Host 'DRY-RUN：没有真的运行。确认无误后加 -Execute。'
            Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'run-dryrun'
                          app_name = [System.IO.Path]::GetFileName($facts.Path)
                          source_url = $facts.Path; sha256 = $facts.Sha256
                          sig_status = $facts.SigStatus; signer = $facts.Signer
                          args = $execDesc; exit_code = 'dryrun'
                          note = ('type=' + $(if ($isMsi) { 'msi' } elseif ($isMsix) { 'msix' } else { 'exe' })) }
            exit 0
        }

        # ---- 1) 装前快照（默认做，-SkipSnapshot 跳过）----
        # 快照失败必须中止：安全网 fail-open 比没有安全网更危险
        if (-not $SkipSnapshot) {
            $snapScript = Join-Path $PSScriptRoot 'snapshot.ps1'
            if (Test-Path -LiteralPath $snapScript) {
                Write-Host ''
                Write-Host '装前快照中（-SkipSnapshot 可跳过）...'
                $snapOut = & pwsh -NoProfile -ExecutionPolicy Bypass -File $snapScript -Label ('preinstall-' + (Get-Date -Format 'HHmmss')) 2>&1
                $snapRc = $LASTEXITCODE
                $snapOut | Select-Object -Last 4 | Write-Host
                if ($snapRc -ne 0) {
                    Write-Host ''
                    Write-Host ("!! 装前快照失败（退出码 {0}）→ 中止安装。" -f $snapRc)
                    Write-Host '   你可能以为已经有保护了，实际没有。'
                    Write-Host '   先修好快照（看 D:\agent-work\logs\snapshot-*.log），'
                    Write-Host '   确实不需要快照才加 -SkipSnapshot 重跑。'
                    Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'abort-no-snapshot'
                                  app_name = [System.IO.Path]::GetFileName($facts.Path)
                                  exit_code = $snapRc
                                  note = 'pre-install snapshot failed, install aborted' }
                    exit 6
                }
                Write-Host '装前快照完成'
            } else {
                Write-Host '（找不到 snapshot.ps1）'
                Write-Host '!! 没有快照脚本 → 中止（要跳过快照请显式加 -SkipSnapshot）'
                exit 6
            }
        }

        # ---- 2) 记录装前程序清单（用于装后对比）----
        $before = Get-InstalledPrograms
        Write-Host ("装前已登记程序: {0} 个" -f @($before).Count)

        # ---- 3) 执行 ----
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $rc = 1
        if ($isMsix) {
            try {
                Add-AppxPackage -Path $facts.Path -ErrorAction Stop
                $rc = 0
            } catch {
                Write-Host ("Add-AppxPackage 失败: {0}" -f $_.Exception.Message)
                $rc = 1
            }
        } elseif ($isMsi) {
            # MSI 往 Program Files 写必须管理员，直接跑会 1603。用提权通道执行。
            Write-Host 'MSI 需要管理员权限，用提权通道执行（本机 UAC 静默，不会弹框）...'
            $rc = Invoke-InstallerElevated -Exe 'msiexec.exe' -ArgList $msiArgs -Reason ("msi-install: " + [System.IO.Path]::GetFileName($facts.Path))
        } else {
            $p = Start-Process -FilePath $facts.Path -ArgumentList $ArgList -Wait -PassThru
            $rc = $p.ExitCode
            # 1603 = MSI 致命错误，5 = 拒绝访问，-99 = 提权通道自身异常
            if (@(1603, 5, -99) -contains $rc) {
                Write-Host ("  退出码 {0} 看起来是权限不足 → 改用管理员重试" -f $rc)
                $rc = Invoke-InstallerElevated -Exe $facts.Path -ArgList $ArgList -Reason ("exe-retry-after-rc" + $rc + ": " + [System.IO.Path]::GetFileName($facts.Path))
            }
        }
        $sw.Stop()

        # ---- 4) 装后验证：注册表里多了什么 ----
        $after = Get-InstalledPrograms
        $newOnes = @(Compare-InstalledPrograms -Before $before -After $after)

        Write-Host ''
        Write-Host ("退出码  : {0}   耗时 {1:N1} 秒" -f $rc, $sw.Elapsed.TotalSeconds)
        if ($newOnes.Count -gt 0) {
            Write-Host ("新增程序: {0} 个" -f $newOnes.Count)
            $newOnes | ForEach-Object {
                Write-Host ("  + {0}  ({1})" -f $_.DisplayName, $_.DisplayVersion)
            }
        } else {
            Write-Host '新增程序: 0 个 —— 说明这次安装没有在注册表登记新程序。'
            Write-Host '  可能原因：① 只是升级（同名程序覆盖） ② 便携版（不解压到注册表）'
            Write-Host '           ③ 安装器静默失败（退出码 0 但什么都没装）'
            Write-Host '           ④ 权限不足 —— MSI 常见 1603，装到 Program Files 必须管理员'
            if (@(1603, 1625, 5) -contains $rc) {
                Write-Host ("  >> 本次退出码 {0} 就是权限问题，先用管理员权限重跑一次再判断。" -f $rc)
            }
            Write-Host '  请手动确认目标软件的版本或安装目录。'
        }

        $uninst = ''
        if ($newOnes.Count -gt 0) {
            $f = $newOnes[0]
            if ($f.QuietUninstallString) { $uninst = $f.QuietUninstallString }
            elseif ($f.UninstallString) { $uninst = $f.UninstallString }
        }

        Add-LogRow @{ timestamp = (Get-Date -Format 'o'); action = 'run'
                      app_name = [System.IO.Path]::GetFileName($facts.Path)
                      version = $(if ($newOnes.Count -gt 0) { [string]$newOnes[0].DisplayVersion } else { '' })
                      source_url = $facts.Path; sha256 = $facts.Sha256
                      sig_status = $facts.SigStatus; signer = $facts.Signer
                      args = $execDesc; exit_code = $rc
                      uninstall_cmd = $uninst
                      note = ('type=' + $(if ($isMsi) { 'msi' } elseif ($isMsix) { 'msix' } else { 'exe' }) +
                              '; new=' + $newOnes.Count) }

        if ($rc -ne 0) { exit 4 }
        exit 0
    }

    'log' {
        if (-not (Test-Path -LiteralPath $LogPath)) {
            Write-Host ("记账本还不存在: {0}" -f $LogPath)
            Write-Host '跑一次 search / show / fetch / verify 就会自动创建。'
            exit 0
        }
        $rows = Import-Csv -LiteralPath $LogPath
        Write-Host ("记账本: {0}（共 {1} 条）" -f $LogPath, $rows.Count)
        Write-Host ''
        $rows | Select-Object -Last $LogLimit |
            Format-Table timestamp, action, app_name, version, sig_status, exit_code -AutoSize |
            Out-String -Width 200 | Write-Host
        exit 0
    }

    'uninstall-info' {
        if (-not $Target) { Write-Host '用法: install.ps1 uninstall-info <软件名片段>'; exit 1 }
        $paths = @(
            'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
        )
        $hits = Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -and $_.DisplayName -like ("*" + $Target + "*") } |
                Select-Object DisplayName, DisplayVersion, UninstallString, QuietUninstallString |
                Sort-Object DisplayName
        if (-not $hits) {
            Write-Host ("注册表里没找到包含 '{0}' 的软件。" -f $Target)
            exit 0
        }
        Write-Host ("找到 {0} 个：" -f @($hits).Count)
        Write-Host ''
        $hits | Format-List | Out-String -Width 250 | Write-Host
        Write-Host '> QuietUninstallString 存在时优先用它（能静默卸载）。'
        exit 0
    }
}