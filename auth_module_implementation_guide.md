# Twitter Reply Bot - Auth部分モジュール化 実装手順書・仕様書

## 🎯 実装目標

**shared_modules/chrome_profile_managerを活用したAuth部分のみのモジュール化**
- Cookie認証 → Profile認証への完全移行
- 既存コードへの影響ゼロ
- 完全後方互換性の維持

---

## 📂 実装対象ファイル一覧

### 🆕 新規作成ファイル
1. `reply_bot/auth/__init__.py`
2. `reply_bot/auth/twitter_profile_auth.py`

### ✏️ 修正対象ファイル  
1. `reply_bot/utils.py` - 内部実装変更（インターフェース維持）
2. `reply_bot/config.py` - 設定項目追加

### 🔒 変更禁止ファイル
- `shared_modules/` 配下の全ファイル（利用のみ）
- その他既存ファイル全て（main.py, csv_generator.py等）

---

## 📝 実装仕様書

### 1. `reply_bot/auth/__init__.py` - 新規作成

```python
"""
Twitter Authentication Module
Profile-based authentication using shared_modules
"""

from .twitter_profile_auth import TwitterProfileAuth

__all__ = ['TwitterProfileAuth']
```

**仕様:**
- シンプルなモジュール初期化
- TwitterProfileAuthクラスのエクスポート

---

### 2. `reply_bot/auth/twitter_profile_auth.py` - 新規作成

#### **クラス仕様: TwitterProfileAuth**

**主要メソッド:**
```python
class TwitterProfileAuth:
    def __init__(self, profiles_dir: str = "./profiles")
    def get_authenticated_driver(self, profile_name: str, headless: bool, force_recreate: bool) -> webdriver.Chrome
    def close_driver(self) -> None
    def setup_initial_profile(self, profile_name: str) -> bool
    def _verify_twitter_access(self, driver: Optional[webdriver.Chrome]) -> bool
```

**重要な実装ポイント:**

1. **shared_modules import方式**
```python
# パス追加でshared_modulesを安全にimport
import sys
from pathlib import Path

shared_modules_path = Path(__file__).parent.parent.parent / "shared_modules" / "chrome_profile_manager"
sys.path.insert(0, str(shared_modules_path))
from chrome_profile_manager import ProfiledChromeManager
```

2. **Driver生存確認**
```python
# 既存Driverの生存確認
try:
    _ = self._current_driver.current_url
    return self._current_driver  # 再利用
except:
    self._current_driver = None  # 新規作成
```

3. **Chrome起動オプション**
```python
chrome_options = {
    'headless': headless,
    'no_sandbox': True,
    'disable_dev_shm_usage': True,
    'disable_gpu': headless,
    'window_size': '1920,1080'
}
```

4. **エラーハンドリング**
```python
try:
    # Driver作成処理
except Exception as e:
    self.logger.error(f"Driver作成中にエラー: {e}")
    if self._current_driver:
        self._current_driver.quit()
        self._current_driver = None
    raise
```

#### **完全実装コード**

```python
"""
Twitter Profile Authentication using shared_modules
既存のutils.pyのWebDriver管理を完全に置き換え
"""

import sys
import os
from pathlib import Path
from typing import Optional
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# shared_modulesへのパス追加
shared_modules_path = Path(__file__).parent.parent.parent / "shared_modules" / "chrome_profile_manager"
sys.path.insert(0, str(shared_modules_path))

from chrome_profile_manager import ProfiledChromeManager

class TwitterProfileAuth:
    """shared_modules/chrome_profile_managerを活用したTwitter認証システム"""
    
    def __init__(self, profiles_dir: str = "./profiles"):
        """
        Args:
            profiles_dir: プロファイル保存ディレクトリ
        """
        self.profile_manager = ProfiledChromeManager(profiles_dir)
        self.logger = logging.getLogger(__name__)
        self._current_driver = None
    
    def get_authenticated_driver(self, 
                               profile_name: str = "twitter_main",
                               headless: bool = True,
                               force_recreate: bool = False) -> webdriver.Chrome:
        """
        認証済みWebDriverインスタンスを取得
        既存のget_driver()とsetup_driver()を置き換え
        
        Args:
            profile_name: 使用するプロファイル名
            headless: ヘッドレスモード
            force_recreate: プロファイルの強制再作成
            
        Returns:
            認証済みWebDriverインスタンス
        """
        try:
            # 既存のDriverが生きているかチェック
            if self._current_driver and not force_recreate:
                try:
                    # WebDriverの生存確認
                    _ = self._current_driver.current_url
                    self.logger.info("既存のDriverを再利用します")
                    return self._current_driver
                except:
                    self.logger.info("既存のDriverが無効なため、新しいDriverを作成します")
                    self._current_driver = None
            
            # shared_modulesを使用してProfile付きDriverを作成
            chrome_options = {
                'headless': headless,
                'no_sandbox': True,
                'disable_dev_shm_usage': True,
                'disable_gpu': headless,
                'window_size': '1920,1080'
            }
            
            self._current_driver = self.profile_manager.create_and_launch(
                profile_name=profile_name,
                force_recreate=force_recreate,
                **chrome_options
            )
            
            # Twitterアクセス可能性の確認
            if self._verify_twitter_access():
                self.logger.info(f"Profile '{profile_name}' で認証済みDriverを取得しました")
                return self._current_driver
            else:
                self.logger.warning(f"Profile '{profile_name}' でのTwitterアクセスに問題があります")
                return self._current_driver
                
        except Exception as e:
            self.logger.error(f"Driver作成中にエラー: {e}")
            if self._current_driver:
                self._current_driver.quit()
                self._current_driver = None
            raise
    
    def close_driver(self):
        """WebDriverを終了"""
        if self._current_driver:
            try:
                self._current_driver.quit()
                self.logger.info("WebDriverを正常に終了しました")
            except Exception as e:
                self.logger.warning(f"WebDriver終了時に警告: {e}")
            finally:
                self._current_driver = None
    
    def setup_initial_profile(self, profile_name: str = "twitter_main") -> bool:
        """
        初回Profile設定（手動ログイン用）
        
        Args:
            profile_name: 作成するプロファイル名
            
        Returns:
            設定成功可否
        """
        try:
            self.logger.info(f"Profile '{profile_name}' の初期設定を開始します")
            
            # 非ヘッドレスで新しいProfileを作成
            driver = self.profile_manager.create_and_launch(
                profile_name=profile_name,
                force_recreate=True,
                headless=False,  # 手動ログイン用
                no_sandbox=True,
                disable_dev_shm_usage=True
            )
            
            # Twitterログインページにアクセス
            driver.get("https://x.com/login")
            
            self.logger.info("手動でログインを完了してください。完了後、このプロファイルが保存されます。")
            input("ログインが完了したらEnterキーを押してください...")
            
            # ログイン確認
            if self._verify_twitter_access(driver):
                self.logger.info(f"Profile '{profile_name}' の設定が完了しました")
                driver.quit()
                return True
            else:
                self.logger.error("ログインが確認できませんでした")
                driver.quit()
                return False
                
        except Exception as e:
            self.logger.error(f"初期Profile設定中にエラー: {e}")
            return False
    
    def _verify_twitter_access(self, driver: Optional[webdriver.Chrome] = None) -> bool:
        """Twitter認証状態の確認"""
        test_driver = driver or self._current_driver
        if not test_driver:
            return False
            
        try:
            test_driver.get("https://x.com/home")
            # ホームページの要素確認（簡易チェック）
            return "x.com/home" in test_driver.current_url
        except:
            return False
```

---

### 3. `reply_bot/utils.py` - 修正仕様

#### **変更方針**
- **インターフェース**: 100%維持（既存関数名・シグネチャ・戻り値）
- **内部実装**: Profile認証に完全移行
- **互換性**: 既存コードから見た挙動は同一

#### **修正対象関数**

**A. `setup_driver(headless: bool = True) -> webdriver.Chrome`**
```python
# 変更前（Cookie方式）
def setup_driver(headless: bool = True):
    global _driver
    # Cookie読み込み処理...
    
# 変更後（Profile方式）
def setup_driver(headless: bool = True) -> webdriver.Chrome:
    auth_manager = _get_auth_manager()
    profile_name = getattr(globals(), 'TWITTER_PROFILE_NAME', 'twitter_main')
    return auth_manager.get_authenticated_driver(
        profile_name=profile_name,
        headless=headless
    )
```

**B. `get_driver(headless: bool = True) -> webdriver.Chrome`**
```python
# シンプルにsetup_driverを呼び出し
def get_driver(headless: bool = True) -> webdriver.Chrome:
    return setup_driver(headless=headless)
```

**C. `close_driver()`**
```python
# 変更前（グローバル変数管理）
def close_driver():
    global _driver
    if _driver:
        _driver.quit()
        _driver = None

# 変更後（AuthManager委譲）
def close_driver():
    auth_manager = _get_auth_manager()
    auth_manager.close_driver()
```

**D. 新規追加: `_get_auth_manager()`**
```python
# グローバル認証マネージャーの遅延初期化
_auth_manager = None

def _get_auth_manager():
    global _auth_manager
    if _auth_manager is None:
        from .auth.twitter_profile_auth import TwitterProfileAuth
        profiles_dir = getattr(globals(), 'PROFILES_DIR', './profiles')
        _auth_manager = TwitterProfileAuth(profiles_dir)
    return _auth_manager
```

#### **保持する既存関数**
```python
# これらの関数は既存のまま維持
def check_memory_usage():  # 既存コード維持
    pass

def force_restart_driver():  # Profile版に内部変更のみ
    """強制再起動（Profile版）"""
    auth_manager = _get_auth_manager()
    auth_manager.close_driver()
    profile_name = getattr(globals(), 'TWITTER_PROFILE_NAME', 'twitter_main')
    return auth_manager.get_authenticated_driver(
        profile_name=profile_name,
        force_recreate=True
    )
```

#### **完全な修正版utils.py**

```python
"""
WebDriver utilities - Profile認証への移行版
既存のインターフェースを維持しながら内部実装を変更
"""

import logging
import pickle
import os
import time
import psutil
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException

from .config import LOGIN_URL, LOGIN_TIMEOUT_ENABLED, LOGIN_TIMEOUT_SECONDS, PAGE_LOAD_TIMEOUT_SECONDS

# 既存のCookie関連は互換性のため残す
COOKIE_FILE = "cookie/twitter_cookies_01.pkl"

# Profile認証用のグローバル変数
_auth_manager = None
_memory_monitor_enabled = True  # メモリ監視の有効/無効フラグ

def _get_auth_manager():
    """認証マネージャーの取得（遅延初期化）"""
    global _auth_manager
    if _auth_manager is None:
        from .auth.twitter_profile_auth import TwitterProfileAuth
        profiles_dir = getattr(globals(), 'PROFILES_DIR', './profiles')
        _auth_manager = TwitterProfileAuth(profiles_dir)
    return _auth_manager

def setup_driver(headless: bool = True) -> webdriver.Chrome:
    """
    WebDriverのセットアップ（既存関数の互換性維持）
    内部実装をProfile認証に変更
    """
    auth_manager = _get_auth_manager()
    profile_name = getattr(globals(), 'TWITTER_PROFILE_NAME', 'twitter_main')
    
    try:
        return auth_manager.get_authenticated_driver(
            profile_name=profile_name,
            headless=headless
        )
    except Exception as e:
        logging.error(f"setup_driver failed: {e}")
        raise

def get_driver(headless: bool = True) -> webdriver.Chrome:
    """
    WebDriverの取得（既存関数の互換性維持）
    """
    return setup_driver(headless=headless)

def close_driver():
    """
    WebDriverの終了（既存関数の互換性維持）
    """
    auth_manager = _get_auth_manager()
    auth_manager.close_driver()

def check_memory_usage():
    """
    現在のプロセスのメモリ使用量を取得（MB単位）
    """
    if not _memory_monitor_enabled:
        return None
        
    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        return memory_mb
    except Exception as e:
        logging.warning(f"メモリ使用量の取得に失敗しました: {e}")
        return None

def force_restart_driver():
    """強制再起動（Profile版）"""
    auth_manager = _get_auth_manager()
    auth_manager.close_driver()
    profile_name = getattr(globals(), 'TWITTER_PROFILE_NAME', 'twitter_main')
    return auth_manager.get_authenticated_driver(
        profile_name=profile_name,
        force_recreate=True
    )
```

---

### 4. `reply_bot/config.py` - 設定追加仕様

#### **追加する設定項目**
```python
# Profile認証関連の新設定（既存設定の後に追加）

# Profile認証設定
TWITTER_PROFILE_NAME = "twitter_main"    # 使用するProfile名
PROFILES_DIR = "./profiles"              # Profile保存ディレクトリ
USE_PROFILE_AUTH = True                  # Profile認証の有効化

# 移行期間中の設定
LEGACY_COOKIE_SUPPORT = False            # Cookie認証のサポート（将来削除）
```

#### **既存設定の保持**
```python
# 既存の全ての設定は完全に維持
TARGET_USER = "Maya19960330"
LOGIN_URL = "https://x.com/login"
USERNAME = "Maya19960330"
PASSWORD = "USHIneko1"
# ... (以下既存設定すべて)
```

---

## 🔄 実装手順

### **Phase 1: ディレクトリ・基本ファイル作成**

#### **Step 1-1: ディレクトリ作成**
```bash
mkdir reply_bot/auth
```

#### **Step 1-2: `__init__.py` 作成**
- 上記仕様通りに作成
- インポートのみの簡単な内容

#### **Step 1-3: `config.py` への設定追加**
- 既存設定の最後に新しい設定を追加
- 既存設定は一切変更しない

### **Phase 2: メインAuthクラス実装**

#### **Step 2-1: `twitter_profile_auth.py` の骨格作成**
```python
# クラス定義と基本メソッドのスケルトン
class TwitterProfileAuth:
    def __init__(self, profiles_dir: str = "./profiles"):
        pass  # 後で実装
    
    def get_authenticated_driver(self, ...):
        pass  # 後で実装
```

#### **Step 2-2: shared_modules連携実装**
```python
# shared_modulesへのパス追加とimport
shared_modules_path = Path(__file__).parent.parent.parent / "shared_modules" / "chrome_profile_manager"
sys.path.insert(0, str(shared_modules_path))
from chrome_profile_manager import ProfiledChromeManager
```

#### **Step 2-3: コアロジック実装**
1. `__init__`: ProfiledChromeManagerの初期化
2. `get_authenticated_driver`: Driver作成・管理
3. `close_driver`: Driver終了
4. `setup_initial_profile`: 初回Profile設定
5. `_verify_twitter_access`: 認証確認

### **Phase 3: utils.py移行**

#### **Step 3-1: 新しいヘルパー関数追加**
```python
# _get_auth_manager() を最初に追加
def _get_auth_manager():
    # 実装内容
```

#### **Step 3-2: 既存関数の内部実装変更**
```python
# 一つずつ関数の中身を変更
# インターフェースは絶対に変更しない
def setup_driver(headless: bool = True):
    # 新しい実装
    
def get_driver(headless: bool = True):
    # 新しい実装
    
def close_driver():
    # 新しい実装
```

### **Phase 4: テスト・動作確認**

#### **Step 4-1: import確認**
```python
# Pythonコンソールで確認
from reply_bot.auth.twitter_profile_auth import TwitterProfileAuth
auth = TwitterProfileAuth()
```

#### **Step 4-2: Profile作成テスト**
```python
# 初回Profile設定の実行
auth = TwitterProfileAuth()
success = auth.setup_initial_profile("twitter_main")
```

#### **Step 4-3: 既存システムとの互換性確認**
```python
# 既存のコードが動作することを確認
from reply_bot.utils import setup_driver
driver = setup_driver(headless=False)
```

---

## ⚠️ 重要な注意事項

### **制約の遵守**
1. **shared_modules修正禁止**: 利用のみ、一切の変更禁止
2. **既存コード無変更**: main.py, csv_generator.py等は一切変更しない
3. **インターフェース維持**: utils.pyの関数シグネチャ・戻り値型を維持

### **安全な実装のためのチェックポイント**
1. **バックアップ作成**: 修正前に既存ファイルをバックアップ
2. **段階的テスト**: 各Phaseごとに動作確認
3. **ロールバック準備**: 問題発生時の戻し方を事前準備

### **テスト項目**
1. **import テスト**: モジュールが正常に読み込めるか
2. **Driver作成テスト**: Profile付きDriverが作成できるか  
3. **Twitter接続テスト**: 認証状態でTwitterにアクセスできるか
4. **既存システムテスト**: 既存のmain.pyが正常動作するか

---

## 📊 実装完了の確認方法

### **成功指標**
1. ✅ `from reply_bot.auth import TwitterProfileAuth` が成功
2. ✅ `setup_driver()` でProfile付きDriverが取得される
3. ✅ TwitterのHome画面にアクセス成功
4. ✅ 既存のmain.pyが無修正で正常動作
5. ✅ shared_modulesが無修正で利用されている

### **失敗時の対処**
- 各Phaseでの問題発生時はロールバック
- ログを確認してエラー原因を特定
- shared_modules連携の問題は、パス設定を再確認

---

## 📋 初回Profile設定の手順

### **実装完了後の初期設定**

```python
# 1. Profile認証システムのテスト
from reply_bot.auth.twitter_profile_auth import TwitterProfileAuth

# 2. 認証マネージャーの作成
auth = TwitterProfileAuth()

# 3. 初回Profile設定の実行（手動ログインが必要）
success = auth.setup_initial_profile("twitter_main")

# 4. 設定完了後、通常のDriverとして利用可能
driver = auth.get_authenticated_driver("twitter_main", headless=False)
```

この実装手順書に従うことで、安全かつ確実にAuth部分のモジュール化が実現できます。