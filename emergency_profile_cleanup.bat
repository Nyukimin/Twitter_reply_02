@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

echo ========================================
echo Chrome Profile Emergency Cleanup
echo ========================================
echo.

echo [1/4] Force terminating all Chrome processes...
echo.
taskkill /F /IM chrome.exe 2>nul
taskkill /F /IM chromedriver.exe 2>nul
powershell -Command "Get-Process | Where-Object {$_.ProcessName -like '*chrome*'} | Stop-Process -Force" 2>nul
wmic process where "name='chrome.exe'" delete 2>nul
timeout /t 3 /nobreak >nul

echo [2/4] Attempting complete profile directory deletion...
echo.
if exist "profiles\twitter_main" (
    echo Taking ownership of profile directory...
    takeown /F "profiles\twitter_main" /R /D Y 2>nul
    echo Granting full permissions...
    icacls "profiles\twitter_main" /grant Everyone:F /T 2>nul
    echo Removing read-only attributes...
    attrib -R /S "profiles\twitter_main\*.*" 2>nul
    echo Deleting profile directory...
    rmdir /S /Q "profiles\twitter_main" 2>nul
    if not exist "profiles\twitter_main" (
        echo Profile directory successfully deleted.
    ) else (
        echo Warning: Some files could not be deleted.
    )
) else (
    echo Profile directory does not exist.
)

echo [3/4] Creating fresh profile directory...
echo.
if not exist "profiles" mkdir "profiles"
mkdir "profiles\twitter_main" 2>nul
echo Fresh profile directory created.

echo [4/4] Final cleanup verification...
echo.
if exist "profiles\twitter_main\SingletonLock" (
    del /F /Q "profiles\twitter_main\SingletonLock"
    echo Removed SingletonLock
)
if exist "profiles\twitter_main\lockfile" (
    del /F /Q "profiles\twitter_main\lockfile"
    echo Removed lockfile
)

echo.
echo ========================================
echo Emergency cleanup completed
echo ========================================
echo.
pause