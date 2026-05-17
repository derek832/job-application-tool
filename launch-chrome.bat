@echo off
:: Launch Chrome with remote debugging for the Job Application Tool.
:: Double-click this file or run it from a terminal.
:: Uses a separate profile so your normal Chrome stays untouched.

set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
set PROFILE_DIR=%LOCALAPPDATA%\ChromeAutomation

if not exist %CHROME_PATH% (
    set CHROME_PATH="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

if not exist %CHROME_PATH% (
    echo Chrome not found. Please install Google Chrome or update the path in this file.
    pause
    exit /b 1
)

echo Starting Chrome with remote debugging on port 9222...
echo Profile: %PROFILE_DIR%
echo.
echo Leave this window open. Close it to stop the automation Chrome.
echo.

start "" %CHROME_PATH% --remote-debugging-port=9222 --user-data-dir="%PROFILE_DIR%" --no-first-run
