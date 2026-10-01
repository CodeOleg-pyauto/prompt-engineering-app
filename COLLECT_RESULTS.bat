@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0collect_results.py" --interactive %*
  goto done
)
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.12 3.13 3.11) do (
    py -%%V -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13)" >nul 2>nul
    if not errorlevel 1 (
      py -%%V "%~dp0collect_results.py" --interactive %*
      goto done
    )
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13)" >nul 2>nul
  if not errorlevel 1 (
    python "%~dp0collect_results.py" --interactive %*
    goto done
  )
)
echo Python 3.11-3.13 is required ONLY on the teacher's computer.
echo Install Python 3.12, then run this file again.
pause
exit /b 1
:done
if errorlevel 1 (
  echo Collection failed. Read the message above.
  pause
  exit /b 1
)
echo.
pause
endlocal
