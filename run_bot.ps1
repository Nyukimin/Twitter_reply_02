param(
  [switch]$ForceClean = $true,  # If true, forcibly terminate existing processes
  [string]$ProfilePath = "C:\GenerativeAI\Twitter_reply\profile\Maya19960330",
  [switch]$UseEphemeralRunProfile = $false,  # Use temporary profile if true
  [string]$PythonExe = "C:\Users\nyuki\miniconda3\envs\TwitterReplyEnv\python.exe",
  [string]$BotName = "Maya19970330_reply"  # Used for Mutex name etc.
)

$Hours = 24
$LiveRun = $true  # Set true if needed
$PythonExe = "C:\Users\nyuki\miniconda3\envs\TwitterReplyEnv\python.exe"

# ===== Utility functions =====
function Get-ChromeProcsForProfile($prof) {
  Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like "*$prof*" }
}

function Get-ChromeDriverForProfile($prof) {
  Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq 'chromedriver.exe' -and $_.CommandLine -like "*$prof*" }
}

function Stop-ProcsUsingProfile($prof) {
  $busyChrome = Get-ChromeProcsForProfile $prof
  $busyDriver = Get-ChromeDriverForProfile $prof

  if ($busyChrome -or $busyDriver) {
    if (-not $ForceClean) {
      Write-Host "Profile in use. Use --ForceClean to terminate."
      if ($busyChrome) { $busyChrome | Select ProcessId, Name, CommandLine | Format-List }
      if ($busyDriver) { $busyDriver | Select ProcessId, Name, CommandLine | Format-List }
      exit 1
    }
    Write-Host "Terminating processes using profile."
    $busyChrome | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    $busyDriver | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  }
}

# ===== Preparation =====
$timestamp = Get-Date -Format yyyyMMdd_HHmmss
$runProfile = if ($UseEphemeralRunProfile) {
  "$ProfilePath`_run_$timestamp"
} else {
  $ProfilePath
}

# Log directory with timestamp
$logDir  = "C:\GenerativeAI\Twitter_reply\log"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$timestamp = Get-Date -Format yyyyMMdd_HHmmss
$logFile = "$logDir\bot_$timestamp.log"

# Write first line to log file for confirmation
Add-Content -LiteralPath $logFile -Value "[$timestamp] RUN START"

Write-Host "[$timestamp] RUNNING MAIN.PY (INCLUDES POST)"

# ===== Prevent multiple launches with Mutex =====
$mutexName = "Global\$BotName"
$createdNew = $false
$mutex = $null
try {
  $mutex = [System.Threading.Mutex]::new($true, $mutexName, [ref]$createdNew)
  if (-not $createdNew) {
    Write-Host "Already running. BotName=$BotName"
    exit 1
  }

  # ===== Check profile usage =====
  Stop-ProcsUsingProfile $runProfile

  # ===== Run Python =====
    $pyArgs = @(
        '-m','reply_bot.main',
        '--timestamp', $timestamp,
        '--hours', $Hours
    )
    & $PythonExe @pyArgs *>> $logFile
    
    if ($LiveRun) { $pyArgs += '--live-run' }
}
finally {
  if ($mutex) {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
  }
}

# Show output and append stdout+stderr to log
& $PythonExe @pyArgs 2>&1 | Tee-Object -FilePath $logFile -Append

# Always record exit code
Add-Content -LiteralPath $logFile -Value "[${(Get-Date).ToString('yyyyMMdd_HHmmss')}]"

