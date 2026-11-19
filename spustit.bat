@echo off
rem ===================================================================
rem  GC-MS Automat - start script (double-click to run).
rem  ASCII only on purpose: Czech characters in .bat files break easily.
rem  No parentheses blocks are used, so folder names like "GC-MS (1)" work.
rem ===================================================================
setlocal

rem This switches into the folder of this script (pushd also works on network drives).
pushd "%~dp0"

rem This stops early if the ZIP was not extracted (Python is missing).
if not exist "python\python.exe" goto :not_extracted

rem This keeps Python isolated: no user packages, UTF-8, temp files inside the app folder.
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
if not exist "runtime\tmp" mkdir "runtime\tmp"
set "TEMP=%CD%\runtime\tmp"
set "TMP=%CD%\runtime\tmp"

title GC-MS Automat
echo Spoustim GC-MS Automat... Toto okno nezavirejte, zavre se samo.
echo.

rem This starts the application and waits until it ends.
"python\python.exe" "app\main.py"
if errorlevel 1 goto :failed
popd
exit /b 0

:failed
echo.
echo Aplikace skoncila s chybou. Popis chyby je vyse a v souboru logs\gcms-automat.log.
pause
popd
exit /b 1

:not_extracted
echo.
echo Nenalezen soubor python\python.exe.
echo Nejprve ZIP rozbalte: pravym tlacitkem na ZIP - "Extrahovat vse..."
echo a pak spustte spustit.bat z rozbalene slozky.
echo.
pause
popd
exit /b 1
