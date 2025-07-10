@echo off
rem スクリプトのあるディレクトリに移動
cd /d "C:\GenerativeAI\Twitter_reply"

rem Conda環境をアクティベート
call conda activate TwitterReplyEnv

rem 日時をファイル名に使える形式で取得 (YYYYMMDD_HHMMSS)
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list') do set datetime=%%I
set timestamp=%datetime:~0,8%_%datetime:~8,6%

rem メインスクリプトをライブモードで実行し、出力をログファイルに追記
echo [%timestamp%] Running bot... >> log/task_scheduler_runs.log
python -m reply_bot.main --live-run >> log/task_scheduler_runs.log 2>&1
echo [%timestamp%] Bot run finished. >> log/task_scheduler_runs.log
echo. >> log/task_scheduler_runs.log 