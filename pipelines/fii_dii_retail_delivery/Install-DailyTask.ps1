param([string]$At = '20:30')
$ErrorActionPreference = 'Stop'
if ((Get-TimeZone).Id -ne 'India Standard Time') {
    throw 'This installer uses an IST local trigger. Run Update-Now.cmd manually or adapt the trigger to your local timezone.'
}
$taskName = 'MarketDeliveryDataDaily'
$runner = Join-Path $PSScriptRoot 'Invoke-MarketPipeline.ps1'
$pythonExe = (& python -c 'import sys; print(sys.executable)').Trim()
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not ($existing.Actions.Arguments -like ('*' + $runner + '*'))) {
    throw 'A different task already uses this name. It has not been changed.'
}
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '" -Mode Update -PythonPath "' + $pythonExe + '" -Wait'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Local Python exchange-data update; no AI/API-credit use. Requires this user to be signed in.' -Force | Out-Null
Write-Output ('Installed daily local data update at ' + $At + ' IST. The computer must be on and this user signed in.')
