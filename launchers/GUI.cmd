@echo off
setlocal
rem No PowerShell association, administrator rights or execution-policy change.
set "AP_PY="
py -3 -c "import sys;sys.exit(sys.version_info < (3,12))" >nul 2>nul
if not errorlevel 1 set "AP_PY=py -3"
if defined AP_PY goto run
python -c "import sys;sys.exit(sys.version_info < (3,12))" >nul 2>nul
if not errorlevel 1 set "AP_PY=python"
if defined AP_PY goto run
echo Archivist requires Python 3.12 or newer.
echo Install Python, then reopen this launcher. See START-HERE.txt.
pause
exit /b 2
:run
%AP_PY% "%~dp0..\archivist.py" gui %*
set "AP_STATUS=%ERRORLEVEL%"
if "%AP_STATUS%"=="0" exit /b 0
echo.
echo Archivist stopped with error %AP_STATUS%. The message above was retained.
pause
exit /b %AP_STATUS%
