# Chrome Profile Manager - "User Data Directory Already in Use" エラー解決

## 概要
Twitter Reply Bot実行時に発生していた「user data directory is already in use」エラーを完全に解決しました。

## 問題の原因
1. **ChromeDriverの重複インストール**: 毎回ChromeDriverを再インストールすることで不要なプロセスが起動
2. **プロセス管理の問題**: 全Chromeプロセスを終了していたため、他のプロファイルに影響
3. **タイミング問題**: WebDriver初期化前にChromeプロセスが起動していた

## 実装した解決策

### 1. ChromeDriverのキャッシュ化
```python
# shared_modules/chrome_profile_manager/chrome_profile_manager/manager.py
self._driver_path = None  # ChromeDriverパスをキャッシュ

if self._driver_path and os.path.exists(self._driver_path):
    return self._driver_path
else:
    # 初回のみインストール
    self._driver_path = ChromeDriverManager().install()
```

### 2. プロファイル特定のプロセス管理
```python
def kill_chrome_using_profile(self, profile_path: str) -> bool:
    """特定のプロファイルを使用しているChromeプロセスのみを終了"""
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] and 'chrome' in proc.info['name'].lower():
            cmdline = proc.cmdline()
            if any(profile_path.lower() in arg.lower() for arg in cmdline):
                proc.terminate()
```

### 3. 詳細なデバッグ機能
- 5つのチェックポイントでプロセス監視
- `--debug`オプションで詳細ログ表示
- Chrome/ChromeDriverプロセスの可視化

## 使用方法

### 基本的な使用
```bash
# 通常実行
python -m reply_bot.check_login_status

# デバッグモード（詳細ログ表示）
python -m reply_bot.check_login_status --debug

# ヘッドレスモード
python -m reply_bot.check_login_status --headless

# デバッグ + ヘッドレス
python -m reply_bot.check_login_status --debug --headless
```

### Chrome Profile Managerの直接使用
```python
from shared_modules.chrome_profile_manager import ProfiledChromeManager

manager = ProfiledChromeManager(
    profile_name="twitter_main",
    profile_base_dir="profiles"
)

# WebDriverの取得（自動的にクリーンアップ実行）
driver = manager.get_driver(headless=False)

# 使用後
driver.quit()
```

## 主な改善点

### ✅ 解決された問題
- 「user data directory is already in use」エラーが発生しない
- 複数のChromeプロファイルが同時実行可能
- 他のChromeインスタンスに影響を与えない

### 🔧 技術的改善
- ChromeDriverの再インストール防止
- プロファイル特定のプロセス終了
- 26個のLOCKファイルの確実な削除
- WebDriver初期化タイミングの最適化

### 📊 デバッグ機能
- Chrome/ChromeDriverプロセスの追跡
- タイミングチェックポイントログ
- プロファイルパスの検証ログ

## トラブルシューティング

### エラーが再発する場合
1. デバッグモードで実行
   ```bash
   python -m reply_bot.check_login_status --debug
   ```

2. ログを確認
   - Chrome関連プロセスの存在確認
   - LOCKファイルの削除状況
   - ChromeDriverのパス

3. 手動でプロファイルをクリーンアップ
   ```python
   from shared_modules.chrome_profile_manager import ProfiledChromeManager
   
   manager = ProfiledChromeManager("twitter_main", "profiles")
   manager._cleanup_profile_locks()
   manager.kill_chrome_using_profile(manager.profile_path)
   ```

## 実装ファイル
- `shared_modules/chrome_profile_manager/chrome_profile_manager/manager.py` - メイン実装
- `reply_bot/check_login_status.py` - デバッグオプション追加
- `reply_bot/utils.py` - WebDriver設定

## テスト結果
- ✅ Windows 11環境で動作確認
- ✅ 複数Chrome プロファイルの同時実行確認
- ✅ 26個のLOCKファイル削除確認
- ✅ ChromeDriver再インストール防止確認

## 今後の拡張
- [ ] Linux/Mac環境でのテスト
- [ ] プロファイル自動バックアップ機能
- [ ] Chrome更新時の自動対応

## 更新履歴
- 2025-09-09: 初版作成
- ChromeDriverキャッシュ化実装
- プロファイル特定プロセス管理実装
- デバッグオプション追加