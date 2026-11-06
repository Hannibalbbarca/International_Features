$ErrorActionPreference = 'Stop'
$record = Join-Path $PSScriptRoot 'data/backfill-process.json'
if (-not (Test-Path -LiteralPath $record)) { throw 'No recorded background backfill process.' }
$state = Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
$targetProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$state.pid)
if (-not $targetProcess) { Write-Output 'Backfill is no longer running.'; exit }
$expected = Join-Path $PSScriptRoot 'marketpipe.py'
if ($targetProcess.CommandLine -notlike ('*' + $expected + '*') -or $targetProcess.CommandLine -notlike '*backfill*') {
    throw 'The recorded PID no longer identifies this backfill. No process was stopped.'
}
Stop-Process -Id ([int]$state.pid)
Write-Output 'Stopped. Downloaded files remain cached. Start-Backfill.cmd resumes without downloading valid files again.'
