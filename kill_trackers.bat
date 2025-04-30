@echo off
echo [KILLER] Attempting to kill tweet_tracker processes...

REM Force kill all relevant Python scripts
for /f "tokens=2 delims=," %%a in ('tasklist /v /fo csv ^| findstr /i "scraper.py"') do taskkill /PID %%a /F
for /f "tokens=2 delims=," %%a in ('tasklist /v /fo csv ^| findstr /i "updater.py"') do taskkill /PID %%a /F
for /f "tokens=2 delims=," %%a in ('tasklist /v /fo csv ^| findstr /i "watchdog"') do taskkill /PID %%a /F

echo [KILLER] Done.
pause