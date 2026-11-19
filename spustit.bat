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

rem This keeps Python isolated: no user packages, UTF-8 text files.
rem (Temp files are redirected inside Python, so the browser is not affected.)
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

title GC-MS Automat
echo Spoustim GC-MS Automat...
echo Toto okno patri k aplikaci a zobrazi se v nem pripadne chyby.
echo Nechte ho otevrene, zavre se samo po ukonceni aplikace.
echo.

rem This starts the application and waits until it ends.
"python\python.exe" "app\main.py"
rem Any exit code other than 0 is an error (also negative crash codes).
if not "%errorlevel%"=="0" goto :failed
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
