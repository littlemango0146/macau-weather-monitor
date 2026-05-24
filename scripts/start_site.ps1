param(
    [int]$Port = 8000,
    [string]$Python = "D:\anaconda\python.exe",
    [switch]$OpenBrowser
)

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Existing = netstat -ano |
    Select-String -Pattern ":$Port" |
    ForEach-Object { ($_ -split "\s+")[-1] } |
    Sort-Object -Unique

foreach ($ProcessId in $Existing) {
    if ($ProcessId -match "^\d+$") {
        Stop-Process -Id ([int]$ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

$Command = "/c `"$Python -m uvicorn app.main:app --host 0.0.0.0 --port $Port > logs\uvicorn.log 2>&1`""
Start-Process -FilePath "cmd.exe" -ArgumentList $Command -WindowStyle Hidden -WorkingDirectory $ProjectDir
Start-Sleep -Seconds 2

$Url = "http://127.0.0.1:$Port"
Write-Host "Macau Weather site is starting: $Url"
Write-Host "Log file: $LogDir\uvicorn.log"

if ($OpenBrowser) {
    Start-Process $Url
}
