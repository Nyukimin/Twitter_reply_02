param(
  [switch]$ForceClean = $true,  # 既存プロセスを強制終了するなら true
  [string]$ProfilePath = "C:\GenerativeAI\Twitter_reply_orchestrator\profile\Maya19960330",
  [switch]$UseEphemeralRunProfile = $false,  # 一時的に別プロファイルで走らせる場合
  [string]$PythonExe = "C:\Users\nyuki\miniconda3\envs\TwitterReplyEnv\python.exe",
  [string]$BotName = "Maya19960330"  # Mutex 名などに使う 並走時の分離に有効
)

$Hours = 180
$LiveRun = $true  # 付けたければ true
$PythonExe = "python.exe"

# ===== ユーティリティ =====
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
      Write-Host " プロファイル使用中のため起動中止 --ForceClean で強制終了可能 "
      if ($busyChrome) { $busyChrome | Select ProcessId, Name, CommandLine | Format-List }
      if ($busyDriver) { $busyDriver | Select ProcessId, Name, CommandLine | Format-List }
      exit 1
    }
    Write-Host " プロファイル使用中のプロセスを強制終了します "
    $busyChrome | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    $busyDriver | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  }
}

# ===== 実行準備 =====
$timestamp = Get-Date -Format yyyyMMdd_HHmmss
$runProfile = if ($UseEphemeralRunProfile) {
  "$ProfilePath`_run_$timestamp"
} else {
  $ProfilePath
}

# ログ保存先 時刻付き
$logDir  = "C:\GenerativeAI\Twitter_reply\log"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$timestamp = Get-Date -Format yyyyMMdd_HHmmss
$logFile = "$logDir\bot_$timestamp.log"

# ここで“必ず行１書いて、ログファイル作成を確認
Add-Content -LiteralPath $logFile -Value "[$timestamp] RUN START (run_bot_02.ps1)"

Write-Host "[$timestamp] RUNNING MAIN.PY (INCLUDES POST)"

# ===== Mutex による多重起動防止 =====
$mutexName = "Global\$BotName"
$createdNew = $false
$mutex = $null
try {
  $mutex = [System.Threading.Mutex]::new($true, $mutexName, [ref]$createdNew)
  if (-not $createdNew) {
    Write-Host " 既に動作中のため起動しません BotName=$BotName "
    exit 1
  }

  # ===== プロファイル使用チェック =====
  Stop-ProcsUsingProfile $runProfile

  # ===== Python 実行 =====
    $pyArgs = @(
        '-m','reply_bot.main',
        '--timestamp', $timestamp,
        '--hours', $Hours  # ここを 24 や 180 など任意に
    )
    & $PythonExe @pyArgs *>> $logFile
    
    if ($LiveRun) { $pyArgs += '--live-run' }  # スイッチなら付ける
}
finally {
  if ($mutex) {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
  }
}

# 画面表示もしつつ stdout+stderr をログへ追記
& $PythonExe @pyArgs 2>&1 | Tee-Object -FilePath $logFile -Append

# 終了コードを必ず記録
Add-Content -LiteralPath $logFile -Value "[${(Get-Date).ToString('yyyyMMdd_HHmmss')}] EXITCODE = $LASTEXITCODE"

