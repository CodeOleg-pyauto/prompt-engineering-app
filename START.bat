@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0bootstrap.py" %*
  goto done
)
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.13 3.12 3.11) do (
    py -%%V -c "import sys; assert sys.maxsize > 2**32" >nul 2>nul
    if not errorlevel 1 (
      py -%%V "%~dp0bootstrap.py" %*
      goto done
    )
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13) and sys.maxsize > 2**32" >nul 2>nul
  if not errorlevel 1 (
    python "%~dp0bootstrap.py" %*
    goto done
  )
)
echo Python 3.11-3.13 64-bit was not found.
echo Install Python from https://www.python.org/downloads/windows/
echo Choose Python 3.12 64-bit and enable "Add python.exe to PATH".
echo Then run START.bat again.
pause
exit /b 1
:done
if errorlevel 1 (
  echo.
  echo Launch or build failed. Read the error above and README.md.
  pause
  exit /b 1
)
endlocal
