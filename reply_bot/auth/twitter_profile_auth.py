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
