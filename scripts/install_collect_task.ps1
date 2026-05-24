param(
    [string]$TaskName = "MacauWeatherCollect",
    [string]$Python = "D:\anaconda\python.exe"
)

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m app.cli collect-once" `
    -WorkingDirectory $ProjectDir

$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Force

Write-Host "Scheduled task created: $TaskName. It runs every 5 minutes."
