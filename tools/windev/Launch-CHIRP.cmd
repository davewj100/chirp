@echo off
cd /d "%~dp0..\..\.."
start "CHIRP Dark Mode Dev" "%CD%\runtime-dark\pythonw.exe" "%~dp0launch.py" %*
