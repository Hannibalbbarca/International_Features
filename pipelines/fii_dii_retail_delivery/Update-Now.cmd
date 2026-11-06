@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Invoke-MarketPipeline.ps1" -Mode Update -Wait
pause
