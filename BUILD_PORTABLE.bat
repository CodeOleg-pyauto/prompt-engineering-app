@echo off
call "%~dp0START.bat" --build
if errorlevel 1 exit /b 1
echo.
echo Build completed. Open dist\MirPrompt\MirPrompt.exe.
echo The portable ZIP is next to this BAT file.
pause
