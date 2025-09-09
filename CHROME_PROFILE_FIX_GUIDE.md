# Chrome Profile エラー解決ガイド

## 問題の概要

Windows環境で他のPCにプロジェクトを移行した際に、以下のエラーが発生することがあります：

```
session not created: probably user data directory is already in use
PermissionError: [Errno 13] assume access denied (originated from ReadProcessMemory -> ERROR_NOACCESS)
```

## 原因

1. **Windows権限問題**: psutilがChromeプロセスのコマンドライン引数を読み取れない
2. **プロファイルロック**: Chromeプロファイルが使用中と誤認識される
3. **プロセス特定失敗**: 特定プロファイルを使用するプロセスを判定できない

## 完全自動解決策

### 1. 自動クリーンアップスクリプトの使用（推奨）

```bash
# シンプル版（推奨）
run_with_cleanup.bat

# デバッグモード
run_with_cleanup.bat --debug

# PowerShell版（詳細ログ）
powershell -ExecutionPolicy Bypass -File run_with_cleanup.ps1
```

これらのスクリプトは以下を自動実行します：
- 特定プロファイルのChromeプロセスのみを終了（他のChromeに影響なし）
- ChromeDriverプロセスを終了
- ロックファイルを削除
- メインプログラムを起動

### 2. 手動対処法（緊急時）

```bash
# 全Chromeプロセスを強制終了
taskkill /F /IM chrome.exe
taskkill /F /IM chromedriver.exe

# プロファイルディレクトリを削除
rmdir /S /Q profiles\twitter_main

# 再実行
python -m reply_bot.check_login_status --debug
```

## 技術的詳細

### Chrome Profile Manager の改善点

1. **PowerShell/WMICを使用した権限回避**
2. **プロファイル別の精密な終了処理**
3. **強力なロックファイルクリーンアップ**
4. **Windows環境特有の問題に対応**

### コード改善箇所

- `shared_modules/chrome_profile_manager/chrome_profile_manager/manager.py`
  - `kill_chrome_using_profile()`: Windows権限エラー対応
  - `_cleanup_profile_locks()`: 強制ロックファイル削除

## 動作確認済み環境

- Windows 11
- Python 3.x
- Chrome/ChromeDriver 最新版

## トラブルシューティング

問題が解決しない場合は：

1. **管理者権限で実行**: コマンドプロンプトを管理者として実行
2. **ウイルス対策ソフトの除外**: プロジェクトフォルダを除外設定に追加
3. **Chromeの完全終了**: タスクマネージャーで全Chromeプロセスを確認

詳細な技術情報は `CHROME_PROFILE_ERROR_ANALYSIS.md` を参照してください。