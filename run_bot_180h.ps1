# PowerShell スクリプト: run_bot.ps1（巻き添え防止版）
# main.py に投稿処理も内包。プロファイル限定の前処理＆終了処理を実装。

param(
  [switch]$ForceClean = $true,  # 既存プロセスを強制終了するなら true
  [string]$ProfilePath = "C:\GenerativeAI\Twitter_reply_orchestrator\profile\Maya19960330",
  [switch]$UseEphemeralRunProfile = $false,  # 一時的に別プロファイルで走らせる場合
  [string]$PythonExe = "C:\Users\nyuki\miniconda3\envs\TwitterReplyEnv\python.exe",
  [string]$BotName = "Maya19960330"  # Mutex 名などに使う（並走時の分離に有効）
)

# セッション開始時に一度だけ
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::UTF8
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# ===== ログファイル =====
$logDir = "C:\GenerativeAI\Twitter_reply_orchestrator\log"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = "$logDir\bot_$(Get-Date -Format yyyyMMdd_HHmmss).log"

# ===== ユーティリティ =====
function Get-ChromeProcsForProfile($prof) {
  Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like "*$prof*" }
}

function Get-ChromeDriverProcs() {
  Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'chromedriver.exe' }
}

# 「このプロファイルを使う chrome.exe の親が chromedriver.exe」のみ抽出
function Get-ChromeDriverForProfile($prof) {
  $chromes = Get-ChromeProcsForProfile $prof
  if (-not $chromes) { return $null }
  $drivers = Get-ChromeDriverProcs
  if (-not $drivers) { return $null }

  $driverByPid = @{}
  foreach ($d in $drivers) { $driverByPid[$d.ProcessId] = $d }

  $driverPids = @{}
  foreach ($c in $chromes) {
    # 親をたどって chromedriver に到達したらその PID を収集
    $cur = $c
    for ($i=0; $i -lt 10 -and $cur -ne $null; $i++) {
      if ($driverByPid.ContainsKey($cur.ParentProcessId)) {
        $driverPids[$cur.ParentProcessId] = $true
        break
      }
      $cur = Get-CimInstance Win32_Process -Filter "ProcessId=$($cur.ParentProcessId)" -ErrorAction SilentlyContinue
    }
  }

  if ($driverPids.Count -gt 0) {
    $drivers | Where-Object { $driverPids.ContainsKey($_.ProcessId) }
  } else {
    $null
  }
}

function Stop-ProcsUsingProfile($prof) {
  $busyChrome = Get-ChromeProcsForProfile $prof
  $busyDriver = Get-ChromeDriverForProfile $prof

  if ($busyChrome -or $busyDriver) {
    if (-not $ForceClean) {
      Write-Host "プロファイル使用中のため起動中止 --ForceClean で強制終了可能"
      $busyChrome | Select ProcessId, Name, CommandLine | Format-List
      $busyDriver | Select ProcessId, Name, CommandLine | Format-List
      exit 1
    }

    # 先に chrome を落としてから driver を落とす
    if ($busyChrome) {
      $busyChrome | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
      Start-Sleep -Milliseconds 500
    }
    if ($busyDriver) {
      $busyDriver | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
      Start-Sleep -Milliseconds 300
    }
  }
}

function Clean-Singleton($prof) {
  if (Test-Path $prof) {
    Get-ChildItem $prof -Filter "Singleton*" -Force -ErrorAction SilentlyContinue |
      Remove-Item -Force -ErrorAction SilentlyContinue
  }
}

# ===== タイムスタンプとログ =====
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = "log"
$logPathUtf8 = "$logDir/task_scheduler_runs_$timestamp.raw.log"
$logPathSjis = "$logDir/task_scheduler_runs_$timestamp.log"
$logPath = "$logDir/task_scheduler_runs_$timestamp.driver.log"

foreach ($d in @($logDir, "source", "output")) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

# ===== 実行ディレクトリ（必要に応じて調整） =====
Set-Location "C:\GenerativeAI\Twitter_reply_orchestrator"

# ===== 実行プロファイル決定 =====
$runProfile = $ProfilePath
if ($UseEphemeralRunProfile) {
  $runProfile = Join-Path $ProfilePath ("run_" + $timestamp)
  New-Item -ItemType Directory -Force -Path $runProfile | Out-Null
}

# ===== 二重起動防止 各ボットで名前を分ける =====
$mutexName = "Global\TwitterReply_$BotName`_LaunchLock"
$mutex = [System.Threading.Mutex]::new($false, $mutexName, [ref]$createdNew)
if (-not $createdNew) {
  Write-Host " 既に起動中 $BotName 終了します "
  exit 1
}

try {
  # ===== プリフライト このプロファイルに限定 =====
  Stop-ProcsUsingProfile $runProfile
  Clean-Singleton $runProfile

  # ===== 起動ログ =====
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$ts][$BotName] RUN MAIN (profile=$runProfile)" | Tee-Object -FilePath $logPathUtf8

  # Python 引数を配列で定義 順番厳守
  $pyArgs = @(
    '-m','reply_bot.main',
    '--timestamp', $timestamp,
    '--hours', 180,             # 変数 $hours を使うならここを $hours に
    '--live-run',
    '--profile', $runProfile,   # 定義済みを想定
    '--bot-name', $BotName      # 定義済みを想定
    )
    
  # 実行 stdout+stderr をまとめて追記
  & $PythonExe @pyArgs *>> $logFile
  
  Tee-Object -FilePath $logPath -Append

  # ===== 終了 ログ =====
  $ts2 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$ts2][$BotName] finished " | Tee-Object -FilePath $logPathUtf8 -Append

  # ===== ログ 変換 =====
  $content = Get-Content -Path $logPathUtf8
  Set-Content -Path $logPathSjis -Value $content -Encoding Default
  Remove-Item $logPathUtf8 -Force -ErrorAction SilentlyContinue

} finally {
  # ===== 終了時の掃除 このプロファイルに限定 =====
  try {
    # 再度、該当プロファイルを掴む chrome とそれに紐づく driver だけ落とす
    Stop-ProcsUsingProfile $runProfile
    if ($UseEphemeralRunProfile) {
      try { Remove-Item -Recurse -Force $runProfile } catch {}
    }
  } catch {}
  if ($mutex) { $mutex.ReleaseMutex(); $mutex.Dispose() }
}
