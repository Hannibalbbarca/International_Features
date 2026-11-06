@echo off
python "%~dp0marketpipe.py" status
if exist "%~dp0data\reports\status.html" start "" "%~dp0data\reports\status.html"
pause
