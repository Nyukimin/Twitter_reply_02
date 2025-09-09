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
import time

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
            
            try:
                self._current_driver = self.profile_manager.create_and_launch(
                    profile_name=profile_name,
                    force_recreate=force_recreate,
                    **chrome_options
                )
            except Exception as e:
                error_msg = str(e).lower()
                if "user data directory is already in use" in error_msg or "session not created" in error_msg:
                    self.logger.warning(f"プロファイル '{profile_name}' が使用中のため、緊急プロファイルで起動します。")
                    
                    # 複数の緊急戦略を順次試行
                    emergency_strategies = [
                        self._try_emergency_profile_v1,
                        self._try_emergency_profile_v2,
                        self._try_emergency_profile_v3
                    ]
                    
                    for i, strategy in enumerate(emergency_strategies):
                        try:
                            self.logger.info(f"緊急戦略 {i+1}/3 を試行中...")
                            self._current_driver = strategy(profile_name, chrome_options)
                            self.logger.info(f"緊急戦略 {i+1} で起動成功")
                            break
                        except Exception as strategy_error:
                            self.logger.warning(f"緊急戦略 {i+1} 失敗: {strategy_error}")
                            if i == len(emergency_strategies) - 1:
                                raise # 最後の戦略も失敗した場合は例外を再発生
                            time.sleep(1)  # 次の戦略前に待機
                else:
                    raise # その他のエラーは再発生
            
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

    
    def _try_emergency_profile_v1(self, base_profile_name: str, chrome_options: dict):
        """緊急戦略1: タイムスタンプ付き一時プロファイル"""
        import datetime
        import uuid
        import time
        
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]  # ミリ秒まで
        unique_id = str(uuid.uuid4())[:8]
        temp_profile_name = f"{base_profile_name}_emg1_{timestamp}_{unique_id}"
        
        return self.profile_manager.create_and_launch(
            profile_name=temp_profile_name,
            force_recreate=True,
            fallback_to_temp=False,  # この戦略ではフォールバック無効
            max_retries=1,
            **chrome_options
        )
    
    def _try_emergency_profile_v2(self, base_profile_name: str, chrome_options: dict):
        """緊急戦略2: 完全分離プロファイル（プロセスID含む）"""
        import datetime
        import os
        import uuid
        
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        pid = os.getpid()
        unique_id = str(uuid.uuid4())[:8]
        temp_profile_name = f"{base_profile_name}_emg2_{timestamp}_{pid}_{unique_id}"
        
        # より長い待機時間
        time.sleep(2)
        
        return self.profile_manager.create_and_launch(
            profile_name=temp_profile_name,
            force_recreate=True,
            fallback_to_temp=False,
            max_retries=1,
            **chrome_options
        )
    
    def _try_emergency_profile_v3(self, base_profile_name: str, chrome_options: dict):
        """緊急戦略3: システム一時ディレクトリ使用"""
        import tempfile
        import os
        import uuid
        import shutil
        
        # システム一時ディレクトリに作成
        temp_base = tempfile.gettempdir()
        unique_id = str(uuid.uuid4())[:8]
        timestamp = int(time.time() * 1000)  # ミリ秒タイムスタンプ
        pid = os.getpid()
        
        temp_dir_name = f"twitter_emergency_{timestamp}_{pid}_{unique_id}"
        temp_profile_path = os.path.join(temp_base, temp_dir_name)
        
        try:
            # 手動でプロファイルディレクトリを作成
            os.makedirs(temp_profile_path, exist_ok=True)
            self.logger.info(f"緊急プロファイル作成: {temp_profile_path}")
            
            # より強力な待機
            time.sleep(3)
            
            # profile_managerを使わずに直接起動
            return self._direct_launch_chrome(temp_profile_path, chrome_options)
            
        except Exception as e:
            # 作成したディレクトリをクリーンアップ
            try:
                if os.path.exists(temp_profile_path):
                    shutil.rmtree(temp_profile_path, ignore_errors=True)
            except:
                pass
            raise e
    
    def _direct_launch_chrome(self, profile_path: str, chrome_options: dict):
        """profile_managerを介さずに直接Chrome起動"""
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from webdriver_manager.chrome import ChromeDriverManager
        import os
        
        # ChromeDriverの取得
        driver_path = ChromeDriverManager().install()
        service = Service(driver_path)
        
        # Chromeオプションの設定
        options = ChromeOptions()
        
        # プロファイル設定
        absolute_profile_path = os.path.abspath(profile_path)
        options.add_argument(f"--user-data-dir={absolute_profile_path}")
        options.add_argument("--profile-directory=Default")
        
        # 基本オプション
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-features=LockProfileData")
        options.add_argument("--disable-features=ProcessSingletonLock")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--no-first-run")
        options.add_argument("--disable-default-apps")
        options.add_argument("--remote-debugging-port=0")
        
        # カスタムオプション適用
        if chrome_options.get('headless', True):
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
        
        if chrome_options.get('window_size'):
            size = chrome_options['window_size']
            if isinstance(size, str):
                options.add_argument(f"--window-size={size}")
            elif isinstance(size, (tuple, list)) and len(size) == 2:
                options.add_argument(f"--window-size={size[0]},{size[1]}")
        
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        self.logger.info(f"緊急戦略3: 直接Chrome起動を開始")
        driver = webdriver.Chrome(service=service, options=options)
        
        return driver
