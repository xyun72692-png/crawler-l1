# 提权修复 hosts：固定 github.com 真实 IP（DNS 被投毒时用）
$ErrorActionPreference = "Continue"
$h = "C:\Windows\System32\drivers\etc\hosts"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = "D:\agent-work\logs\_fix_hosts_$stamp.txt"

"=== 备份 ===" | Out-File $log -Encoding UTF8
$bak = "$h.bak-$stamp"
try {
    Copy-Item $h $bak -Force -ErrorAction Stop
    "备份成功: $bak" | Out-File $log -Append -Encoding UTF8
} catch {
    "备份失败: $($_.Exception.Message)" | Out-File $log -Append -Encoding UTF8
}

"=== 追加 ===" | Out-File $log -Append -Encoding UTF8
$add = @("140.82.112.3 github.com", "140.82.112.3 www.github.com")
$cur = Get-Content $h -Raw
foreach ($l in $add) {
    if ($cur -notmatch [regex]::Escape($l)) {
        Add-Content $h $l -ErrorAction SilentlyContinue
        "追加: $l" | Out-File $log -Append -Encoding UTF8
    } else {
        "已存在: $l" | Out-File $log -Append -Encoding UTF8
    }
}

"=== flushdns ===" | Out-File $log -Append -Encoding UTF8
ipconfig /flushdns 2>&1 | Out-File $log -Append -Encoding UTF8

"=== 当前 hosts 里的 github ===" | Out-File $log -Append -Encoding UTF8
Select-String -Path $h -Pattern "github" | ForEach-Object { $_.Line } | Out-File $log -Append -Encoding UTF8

Get-Content $log