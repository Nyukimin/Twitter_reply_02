@echo off
chcp 65001 > nul
REM Twitter Reply Bot Startup Script with Auto-Cleanup

echo ========================================
echo Twitter Reply Bot Startup Preparation
echo ========================================
echo.

REM Kill Chrome processes using specific profile
echo [1/3] Searching and terminating Chrome processes for specific profile...

REM Use PowerShell to terminate profile-specific processes only
powershell -ExecutionPolicy Bypass -Command "Get-WmiObject Win32_Process | Where-Object { $_.Name -like '*chrome*' -and $_.CommandLine -like '*profiles\\twitter_main*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host 'Terminated Chrome PID:' $_.ProcessId }" 2>nul

REM Terminate ChromeDriver processes
taskkill /F /IM chromedriver.exe 2>nul

echo.
echo [2/3] Cleaning up lock files...

REM Delete lock files in profile directory
if exist "profiles\twitter_main\SingletonLock" del /F /Q "profiles\twitter_main\SingletonLock" 2>nul
if exist "profiles\twitter_main\SingletonSocket" del /F /Q "profiles\twitter_main\SingletonSocket" 2>nul
if exist "profiles\twitter_main\SingletonCookie" del /F /Q "profiles\twitter_main\SingletonCookie" 2>nul
if exist "profiles\twitter_main\Default\SingletonLock" del /F /Q "profiles\twitter_main\Default\SingletonLock" 2>nul
if exist "profiles\twitter_main\Default\SingletonSocket" del /F /Q "profiles\twitter_main\Default\SingletonSocket" 2>nul
if exist "profiles\twitter_main\Default\SingletonCookie" del /F /Q "profiles\twitter_main\Default\SingletonCookie" 2>nul

REM Delete other lock file patterns
for /R "profiles\twitter_main" %%f in (*.lock) do del /F /Q "%%f" 2>nul
for /R "profiles\twitter_main" %%f in (lockfile*) do del /F /Q "%%f" 2>nul
for /R "profiles\twitter_main" %%f in (parent.lock) do del /F /Q "%%f" 2>nul

echo.
echo [3/3] Starting Twitter Reply Bot...
echo.

REM Execute main command with arguments
python -m reply_bot.check_login_status %*

echo.
echo ========================================
echo Process completed
echo ========================================
pause