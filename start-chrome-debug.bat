@echo off
REM Launch Chrome with remote debugging enabled for the job automator.
REM This uses a separate profile so it doesn't affect your normal browsing.
REM Chrome does NOT need to be in focus — it can run in the background.

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --remote-debugging-address=0.0.0.0 ^
  --remote-allow-origins=* ^
  --user-data-dir="%USERPROFILE%\AppData\Local\Google\Chrome\AutomatorProfile" ^
  --no-first-run ^
  --no-default-browser-check ^
  --disable-background-timer-throttling ^
  --disable-backgrounding-occluded-windows ^
  https://www.linkedin.com

echo Waiting for Chrome to start...
timeout /t 3 /nobreak >nul

REM Fetch the WebSocket URL and rewrite to use IP that Docker containers can reach
REM Docker Desktop resolves host.docker.internal to 192.168.65.254 inside containers
echo Fetching Chrome debug WebSocket URL...
powershell -Command "$r = Invoke-WebRequest -Uri http://127.0.0.1:9222/json/version -UseBasicParsing; $ws = ($r.Content | ConvertFrom-Json).webSocketDebuggerUrl; $ws = $ws -replace '127.0.0.1','192.168.65.254'; Set-Content -Path '%~dp0data\chrome-ws-url.txt' -Value $ws -NoNewline; Write-Host \"WebSocket URL: $ws\""

echo.
echo Chrome is ready. You can minimize this window.
echo Log into LinkedIn in the Chrome window if not already logged in.
pause
