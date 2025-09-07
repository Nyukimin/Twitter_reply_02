# Chrome起動エラー解決ガイド

## エラー内容
```
Lock file can not be created! Error code: 5
Failed to create a ProcessSingleton for your profile directory
```

## 解決方法

### 方法1: 管理者権限で実行
```powershell
# PowerShellを管理者として実行
# その後、以下のコマンドを実行
python -m reply_bot.check_login_status
```

### 方法2: プロファイルディレクトリの権限を修正
```powershell
# プロファイルディレクトリに完全な権限を付与
icacls "profiles\twitter_main" /grant:r "%USERNAME%:(OI)(CI)F" /T
```

### 方法3: 既存のChromeプロセスを完全に終了
```powershell
# すべてのChromeプロセスを強制終了
taskkill /F /IM chrome.exe /T
taskkill /F /IM chromedriver.exe /T

# プロファイルディレクトリをクリーンアップ
rmdir /s /q "profiles\twitter_main"

# 再実行
python -m reply_bot.check_login_status
```

### 方法4: 一時的な別プロファイルを使用
環境変数を設定して、一時プロファイルを使用:
```powershell
# 環境変数を設定
$env:TEMP_CHROME_PROFILE="C:\temp\chrome_profile"

# 実行
python -m reply_bot.check_login_status
```

### 方法5: コード側の対策（実装済み）
`manager.py` に以下の対策を実装済み:
- 絶対パスの使用
- SingletonLock機能の無効化
- Windows専用オプションの追加
- ランダムデバッグポートの使用

### 推奨される手順
1. まず、すべてのChromeプロセスを終了
2. プロファイルディレクトリを削除
3. 管理者権限でコマンドプロンプトを起動
4. コマンドを実行

### それでも解決しない場合
プロファイルを使用しないシンプルモードで実行:
```python
# utils.py を一時的に修正して、プロファイルを使用しない
# または環境変数で制御
```

## トラブルシューティング

### 権限の確認
```powershell
# 現在のユーザーの権限を確認
whoami /priv

# プロファイルディレクトリの権限を確認
icacls "profiles\twitter_main"
```

### Chromeのバージョン確認
```powershell
# Chromeのバージョンを確認
"C:\Program Files\Google\Chrome\Application\chrome.exe" --version

# ChromeDriverのバージョンを確認
python -c "from selenium import webdriver; print(webdriver.__version__)"
```

### ログの確認
Chrome起動時の詳細ログを有効化:
```python
# manager.py に追加可能
options.add_argument("--enable-logging")
options.add_argument("--log-level=0")
options.add_argument("--dump-dom")
```

## 代替案: プロファイルレスモード

一時的な解決策として、プロファイルを使用しないモードを追加することも可能:

```python
def setup_driver_simple():
    """プロファイルを使用しないシンプルなドライバー設定"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    driver = webdriver.Chrome(options=options)
    return driver
```

## 最終手段: WSL2での実行

Windows Subsystem for Linux 2 (WSL2) を使用して、Linux環境で実行することも可能です。