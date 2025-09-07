# Chrome Profile Setup - トラブルシューティングガイド

## 🚨 発生したエラー

```
Chrome起動エラー: session not created: probably user data directory is already in use
```

## 🔧 解決方法

### 方法1: 既存Chromeプロセスの終了

```bash
# すべてのChromeプロセスを終了
taskkill /f /im chrome.exe
taskkill /f /im chromedriver.exe
```

### 方法2: ユニークなプロファイル名での再試行

```python
# 異なるプロファイル名で再試行
from reply_bot.auth.twitter_profile_auth import TwitterProfileAuth
auth = TwitterProfileAuth()

# タイムスタンプ付きのユニークな名前を使用
import time
unique_name = f"twitter_main_{int(time.time())}"
success = auth.setup_initial_profile(unique_name)
print(f'Profile setup completed: {success}')
```

### 方法3: プロファイルディレクトリの手動クリーンアップ

```bash
# プロファイルディレクトリを削除して再作成
rmdir /s profiles
mkdir profiles
```

## 🔄 推奨手順

1. **すべてのChromeプロセスを終了**
   ```bash
   taskkill /f /im chrome.exe
   taskkill /f /im chromedriver.exe
   ```

2. **プロファイルディレクトリをクリーンアップ**
   ```bash
   rmdir /s profiles
   mkdir profiles
   ```

3. **初回セットアップを再実行**
   ```python
   conda activate TwitterReplyEnv
   python -c "
   from reply_bot.auth.twitter_profile_auth import TwitterProfileAuth
   auth = TwitterProfileAuth()
   success = auth.setup_initial_profile('twitter_main')
   print(f'Profile setup completed: {success}')
   "
   ```

## 💡 代替セットアップ方法

既存の手動ログイン機能が問題の場合、以下の簡易セットアップも利用可能：

```python
# 既存のCookieベース認証と並行して利用
from reply_bot.utils import setup_driver

# Profile認証でDriverを取得（内部で自動的にProfile作成）
driver = setup_driver(headless=False)
print("Profile認証でのDriver取得成功")

# 手動でTwitterにアクセスしてログイン確認
driver.get("https://x.com/login")
# ここで手動ログイン

# 完了後
from reply_bot.utils import close_driver
close_driver()
```

## 📝 注意事項

- Chrome/ChromeDriverが既に起動している場合は必ず終了してから実行
- プロファイルディレクトリ（`./profiles`）に既存データがある場合は削除を推奨
- セットアップ時は必ず **非ヘッドレスモード** でブラウザを起動
- ログイン完了後、ブラウザを手動で閉じずにEnterキーで完了を通知

---

**トラブルシューティング日時**: 2025年9月7日  
**対象**: Chrome Profile初回セットアップエラー  
**解決策**: プロセス終了 + プロファイルクリーンアップ  
