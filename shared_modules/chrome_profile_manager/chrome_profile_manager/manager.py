"""ProfiledChromeManager - プロファイル作成とChrome起動を統合管理するメインクラス"""

from typing import Optional, Dict, List, Union, Tuple
from pathlib import Path
import os
import shutil
import json
import time
import logging

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager

from .exceptions import ProfileNotFoundError, ProfileCreationError, ChromeLaunchError


class ProfiledChromeManager:
    """プロファイル作成とChrome起動を統合管理する汎用クラス"""
    
    def __init__(self, base_profiles_dir: str = "./profiles"):
        """
        Args:
            base_profiles_dir: プロファイル格納ベースディレクトリ
        """
        self.base_profiles_dir = Path(base_profiles_dir)
        self.base_profiles_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        
    def create_and_launch(
        self, 
        profile_name: str,
        force_recreate: bool = False,
        **chrome_options
    ) -> webdriver.Chrome:
        """プロファイル作成→Chrome起動を一括実行
        
        Args:
            profile_name: プロファイル名
            force_recreate: プロファイルを強制再作成するか
            **chrome_options: Chrome起動オプション
            
        Returns:
            webdriver.Chrome: Chrome WebDriverインスタンス
        """
        try:
            profile_path = self.create_profile(profile_name, force_recreate)
            return self.launch_with_profile(profile_path, **chrome_options)
        except Exception as e:
            self.logger.error(f"プロファイル作成・起動エラー: {e}")
            raise ChromeLaunchError(f"プロファイル '{profile_name}' の作成・起動に失敗: {e}")
    
    def launch_existing(self, profile_name: str, **chrome_options) -> webdriver.Chrome:
        """既存プロファイルでChrome起動
        
        Args:
            profile_name: 既存のプロファイル名
            **chrome_options: Chrome起動オプション
            
        Returns:
            webdriver.Chrome: Chrome WebDriverインスタンス
            
        Raises:
            ProfileNotFoundError: プロファイルが見つからない場合
        """
        profile_path = self.base_profiles_dir / profile_name
        if not profile_path.exists():
            raise ProfileNotFoundError(f"プロファイル '{profile_name}' が見つかりません")
        
        return self.launch_with_profile(str(profile_path), **chrome_options)
    
    def create_profile(self, profile_name: str, force_recreate: bool = False) -> str:
        """プロファイルディレクトリを作成
        
        Args:
            profile_name: プロファイル名
            force_recreate: 強制再作成フラグ
            
        Returns:
            str: 作成されたプロファイルのパス
            
        Raises:
            ProfileCreationError: プロファイル作成に失敗した場合
        """
        profile_path = self.base_profiles_dir / profile_name
        
        try:
            if profile_path.exists() and force_recreate:
                shutil.rmtree(profile_path)
            
            if not profile_path.exists():
                profile_path.mkdir(parents=True, exist_ok=True)
                self._setup_default_preferences(profile_path)
                self.logger.info(f"プロファイル作成完了: {profile_path}")
            
            return str(profile_path)
            
        except Exception as e:
            self.logger.error(f"プロファイル作成エラー: {e}")
            raise ProfileCreationError(f"プロファイル '{profile_name}' の作成に失敗: {e}")
    
    def launch_with_profile(
        self, 
        profile_path: str, 
        **options
    ) -> webdriver.Chrome:
        """指定プロファイルでChromeを起動
        
        Args:
            profile_path: プロファイルパス
            **options: Chrome起動オプション
            
        Returns:
            webdriver.Chrome: Chrome WebDriverインスタンス
            
        Raises:
            ChromeLaunchError: Chrome起動に失敗した場合
        """
        try:
            chrome_options = self._build_chrome_options(profile_path, **options)
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            self.logger.info(f"Chrome起動成功: プロファイル={profile_path}")
            return driver
            
        except Exception as e:
            self.logger.error(f"Chrome起動エラー: {e}")
            raise ChromeLaunchError(f"Chrome起動に失敗: {e}")
    
    def _build_chrome_options(self, profile_path: str, **custom_options) -> ChromeOptions:
        """ChromeOptionsを動的に構築
        
        Args:
            profile_path: プロファイルパス
            **custom_options: カスタムオプション
            
        Returns:
            ChromeOptions: 構築されたChromeオプション
        """
        options = ChromeOptions()
        
        # プロファイル設定
        options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument("--profile-directory=Default")
        
        # 基本ステルス設定
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # カスタムオプション適用
        if custom_options.get('headless', False):
            options.add_argument("--headless")
        
        if 'window_size' in custom_options:
            if isinstance(custom_options['window_size'], (tuple, list)) and len(custom_options['window_size']) == 2:
                w, h = custom_options['window_size']
                options.add_argument(f"--window-size={w},{h}")
        
        if 'user_agent' in custom_options:
            options.add_argument(f"--user-agent={custom_options['user_agent']}")
        
        if 'proxy' in custom_options:
            options.add_argument(f"--proxy-server={custom_options['proxy']}")
        
        if custom_options.get('disable_images', False):
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)
        
        if custom_options.get('disable_javascript', False):
            prefs = options.experimental_options.get("prefs", {})
            prefs["profile.managed_default_content_settings.javascript"] = 2
            options.add_experimental_option("prefs", prefs)
        
        return options
    
    def list_profiles(self) -> List[str]:
        """利用可能なプロファイル一覧を取得
        
        Returns:
            List[str]: プロファイル名のリスト
        """
        try:
            return [p.name for p in self.base_profiles_dir.iterdir() if p.is_dir()]
        except Exception as e:
            self.logger.error(f"プロファイル一覧取得エラー: {e}")
            return []
    
    def delete_profile(self, profile_name: str) -> bool:
        """プロファイルを削除
        
        Args:
            profile_name: 削除するプロファイル名
            
        Returns:
            bool: 削除成功/失敗
        """
        try:
            profile_path = self.base_profiles_dir / profile_name
            if profile_path.exists():
                shutil.rmtree(profile_path)
                self.logger.info(f"プロファイル削除完了: {profile_name}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"プロファイル削除エラー: {e}")
            return False
    
    def backup_profile(self, profile_name: str, backup_name: str = None) -> str:
        """プロファイルをバックアップ
        
        Args:
            profile_name: バックアップ元のプロファイル名
            backup_name: バックアップ名（省略時は自動生成）
            
        Returns:
            str: バックアップパス
            
        Raises:
            ProfileNotFoundError: プロファイルが見つからない場合
        """
        if not backup_name:
            backup_name = f"{profile_name}_backup_{int(time.time())}"
        
        source_path = self.base_profiles_dir / profile_name
        backup_path = self.base_profiles_dir / backup_name
        
        if not source_path.exists():
            raise ProfileNotFoundError(f"プロファイル '{profile_name}' が見つかりません")
        
        try:
            shutil.copytree(source_path, backup_path)
            self.logger.info(f"プロファイルバックアップ完了: {profile_name} -> {backup_name}")
            return str(backup_path)
        except Exception as e:
            self.logger.error(f"プロファイルバックアップエラー: {e}")
            raise ProfileCreationError(f"バックアップに失敗: {e}")
    
    def _setup_default_preferences(self, profile_path: Path) -> None:
        """デフォルトのプロファイル設定を作成
        
        Args:
            profile_path: プロファイルパス
        """
        try:
            # デフォルトのPreferencesファイルを作成
            prefs_path = profile_path / "Default"
            prefs_path.mkdir(exist_ok=True)
            
            preferences = {
                "profile": {
                    "default_content_setting_values": {
                        "notifications": 2,  # 通知ブロック
                        "plugins": 2,        # プラグインブロック
                        "popups": 2,         # ポップアップブロック
                        "geolocation": 2     # 位置情報ブロック
                    }
                }
            }
            
            prefs_file = prefs_path / "Preferences"
            with open(prefs_file, 'w', encoding='utf-8') as f:
                json.dump(preferences, f, indent=2)
                
        except Exception as e:
            self.logger.warning(f"デフォルト設定の作成に失敗: {e}")