param(
    [ValidateSet('Backfill', 'Update', 'Status', 'Report')][string]$Mode = 'Update',
    [string]$PythonPath = '',
    [switch]$Wait
)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) {
    $PythonPath = (& python -c 'import sys; print(sys.executable)').Trim()
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Python 3.10 or newer is required.' }
$scriptPath = Join-Path $PSScriptRoot 'marketpipe.py'
$taskData = Join-Path $PSScriptRoot 'data'
$logDir = Join-Path $taskData 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$taskArgs = @(('"' + $scriptPath + '"'), '--data-dir', ('"' + $taskData + '"'))
if ($Mode -eq 'Backfill') {
    $indiaNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'India Standard Time')
    $endDate = $indiaNow.Date
    if ($indiaNow.Hour -lt 20) { $endDate = $endDate.AddDays(-1) }
    $startDate = $endDate.AddYears(-10)
    $taskArgs += @('backfill', '--start', $startDate.ToString('yyyy-MM-dd'), '--end', $endDate.ToString('yyyy-MM-dd'))
} elseif ($Mode -eq 'Update') {
    $taskArgs += @('update', '--lookback', '10', '--refresh')
} else {
    $taskArgs += $Mode.ToLowerInvariant()
    & $PythonPath $scriptPath --data-dir $taskData ($Mode.ToLowerInvariant())
    exit $LASTEXITCODE
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$launch = @{
    FilePath = $PythonPath
    ArgumentList = $taskArgs
    WorkingDirectory = $PSScriptRoot
    WindowStyle = 'Hidden'
    RedirectStandardOutput = (Join-Path $logDir ($Mode.ToLowerInvariant() + '-' + $stamp + '.log'))
    RedirectStandardError = (Join-Path $logDir ($Mode.ToLowerInvariant() + '-' + $stamp + '.error.log'))
    PassThru = $true
}
if ($Wait) { $launch.Wait = $true }
$process = Start-Process @launch
if ($Mode -eq 'Backfill' -and -not $Wait) {
    @{ pid = $process.Id; script = $scriptPath; started = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskData 'backfill-process.json') -Encoding utf8
}
Write-Output ('Process: ' + $process.Id)
Write-Output ('Log: ' + $launch.RedirectStandardOutput)
Write-Output ('Status page: ' + (Join-Path $taskData 'reports/status.html'))
if ($Wait) { exit $process.ExitCode }
