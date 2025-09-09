@echo off
chcp 65001 >nul
echo ========================================
echo Chrome ^& ChromeDriver Version Check
echo ========================================
echo.

echo [ChromeDriver Version]
"fixed_chrome\chromedriver\chromedriver-win64\chromedriver.exe" --version
echo.

echo [Chrome.exe Version]
powershell -Command "(Get-ItemProperty 'fixed_chrome\chrome\chrome-win64\chrome.exe').VersionInfo.FileVersion"
echo.

echo ========================================
echo Please check version compatibility
echo Major versions (first 3 digits) should match
echo ========================================
pause