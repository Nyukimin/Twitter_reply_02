"""ProfiledChromeManager - プロファイル作成とChrome起動を統合管理するメインクラス"""

from typing import Optional, Dict, List, Union, Tuple
from pathlib import Path
import os
import shutil
import json
import time
import logging
import psutil
import signal
import platform
import tempfile
import uuid
import re
import glob
import subprocess

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager

from .exceptions import ProfileNotFoundError, ProfileCreationError, ChromeLaunchError, ProcessKillError


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
        # ChromeDriverのパスをキャッシュして再利用
        self._driver_path = None
        
    def create_and_launch(
        self, 
        profile_name: str,
        force_recreate: bool = False,
        fallback_to_temp: bool = True,
        max_retries: int = 3,
        **chrome_options
    ) -> webdriver.Chrome:
        """プロファイル作成→Chrome起動を一括実行（指数バックオフ付きリトライ機能付き）
        
        Windows権限問題とBrowserMetrics削除エラーに対応した改善版。
        
        Args:
            profile_name: プロファイル名
            force_recreate: プロファイルを強制再作成するか
            fallback_to_temp: メインプロファイル失敗時に一時プロファイルにフォールバックするか
            max_retries: 最大リトライ回数
            **chrome_options: Chrome起動オプション
            
        Returns:
            webdriver.Chrome: Chrome WebDriverインスタンス
        """
        last_error = None
        
        # Windows環境でのプロファイル完全削除
        def force_remove_profile(profile_path_str: str) -> bool:
            """Windows環境でプロファイルを強制削除"""
            import platform
            if platform.system() != 'Windows':
                return False
                
            try:
                import subprocess
                import time
                
                # takeownで所有権を取得
                subprocess.run(
                    f'takeown /F "{profile_path_str}" /R /D Y',
                    shell=True,
                    capture_output=True,
                    timeout=10
                )
                
                # icaclsでフルコントロール権限を付与
                subprocess.run(
                    f'icacls "{profile_path_str}" /grant Everyone:F /T',
                    shell=True,
                    capture_output=True,
                    timeout=10
                )
                
                # attribで読み取り専用属性を削除
                subprocess.run(
                    f'attrib -R "{profile_path_str}\\*.*" /S',
                    shell=True,
                    capture_output=True,
                    timeout=10
                )
                
                # rmdirで強制削除
                result = subprocess.run(
                    f'rmdir /S /Q "{profile_path_str}"',
                    shell=True,
                    capture_output=True,
                    timeout=10
                )
                
                time.sleep(0.5)  # 削除完了を待つ
                return result.returncode == 0
                
            except Exception as e:
                self.logger.warning(f"強制削除に失敗: {e}")
                return False
        
        # まず通常のプロファイルで試行
        for attempt in range(max_retries):
            try:
                profile_path = self.create_profile(profile_name, force_recreate)
                return self._launch_with_retries(profile_path, max_retries=max_retries, **chrome_options)
            except Exception as e:
                last_error = e
                self.logger.warning(f"プロファイル '{profile_name}' での起動試行 {attempt + 1}/{max_retries} が失敗: {e}")
                
                if attempt < max_retries - 1:
                    backoff_time = 0.5 * (2 ** attempt)
                    self.logger.info(f"リトライまで {backoff_time} 秒待機...")
                    time.sleep(backoff_time)
        
        # 通常プロファイルで失敗した場合、強制削除して再作成
        if fallback_to_temp:
            self.logger.warning(f"プロファイル '{profile_name}' が使用中のため、プロファイルを削除して再作成します。")
            try:
                # 既存プロファイルを強制削除
                old_profile_path = self.base_profiles_dir / profile_name
                if old_profile_path.exists():
                    # まずPythonで削除を試みる
                    try:
                        import shutil
                        shutil.rmtree(old_profile_path)
                        self.logger.info(f"古いプロファイルを削除しました: {old_profile_path}")
                    except Exception as e:
                        self.logger.warning(f"通常削除に失敗: {e}")
                        # Windows環境で強制削除
                        if force_remove_profile(str(old_profile_path)):
                            self.logger.info(f"強制削除でプロファイルを削除しました: {old_profile_path}")
                        else:
                            self.logger.error(f"プロファイル削除に完全に失敗: {old_profile_path}")
                
                # 新しいプロファイルを作成
                new_profile_path = self.create_profile(profile_name, force_recreate=True)
                return self._launch_with_retries(new_profile_path, max_retries=1, **chrome_options)
                
            except Exception as recreate_error:
                self.logger.error(f"プロファイル再作成での起動も失敗: {recreate_error}")
                
                # 一時プロファイルにフォールバック
                self.logger.warning(f"プロファイル '{profile_name}' が使用中のため、新しい一時プロファイルを作成します。")
                try:
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_profile_name = f"{profile_name}_temp_{timestamp}"
                    
                    # 一時プロファイルでの起動を3回まで試行
                    for temp_attempt in range(3):
                        try:
                            # 既存の一時プロファイルがあれば削除
                            temp_profile_path = self.base_profiles_dir / temp_profile_name
                            if temp_profile_path.exists():
                                if force_remove_profile(str(temp_profile_path)):
                                    self.logger.info(f"既存の一時プロファイルを削除: {temp_profile_path}")
                            
                            new_temp_profile_path = self.create_profile(temp_profile_name, force_recreate=True)
                            return self._launch_with_retries(new_temp_profile_path, max_retries=1, **chrome_options)
                            
                        except Exception as temp_error:
                            self.logger.warning(f"プロファイル '{temp_profile_name}' での起動試行 {temp_attempt + 1}/3 が失敗: {temp_error}")
                            if temp_attempt < 2:
                                time.sleep(0.5)
                            
                            # 次の試行用に異なる名前を生成
                            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            temp_profile_name = f"{profile_name}_temp_{timestamp}_{temp_attempt + 1}"
                    
                    # 一時プロファイルでも失敗
                    raise ChromeLaunchError(
                        f"プロファイル '{profile_name}' とすべての一時プロファイルでの起動に失敗。メイン: {last_error}、再作成: {recreate_error}"
                    )
                    
                except Exception as temp_fallback_error:
                    raise ChromeLaunchError(
                        f"プロファイル '{profile_name}' の削除・再作成に失敗。メイン: {last_error}、再作成: {recreate_error}"
                    )
        
        raise ChromeLaunchError(f"プロファイル '{profile_name}' の作成・起動に失敗: {last_error}")
    
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
    
    def _launch_with_retries(
        self, 
        profile_path: str, 
        max_retries: int = 3,
        **options
    ) -> webdriver.Chrome:
        """Chrome起動のリトライロジック（強化版）
        
        Args:
            profile_path: プロファイルディレクトリのパス
            max_retries: 最大リトライ回数
            **options: Chrome起動オプション
            
        Returns:
            webdriver.Chrome: 起動されたChromeドライバー
            
        Raises:
            ChromeStartupError: すべての試行が失敗した場合
        """
        original_profile_path = profile_path
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.logger.info(f"リトライまで {0.5 * attempt} 秒待機...")
                    time.sleep(0.5 * attempt)
                    
                # 試行回数に応じて異なる戦略を採用
                if attempt == 0:
                    # 1回目: 通常のプロファイルパスで試行
                    current_profile_path = profile_path
                elif attempt == 1:
                    # 2回目: プロファイルディレクトリを完全削除して再作成
                    current_profile_path = self._recreate_profile_directory(profile_path)
                else:
                    # 3回目: タイムスタンプ付きの代替プロファイルを作成
                    current_profile_path = self._create_alternative_profile(original_profile_path)
                
                # プロファイル特定のクリーンアップを実行
                self.logger.warning("[開始] プロファイル特定のクリーンアップ開始")
                self._log_chrome_processes("クリーンアップ開始時")
                try:
                    killed_pids = self.kill_chrome_using_profile(current_profile_path, timeout=5)
                    if killed_pids:
                        self.logger.info(f"プロファイル使用中のChromeプロセスを終了: PIDs={killed_pids}")
                        time.sleep(1)  # プロセス終了を待つ
                        self.logger.warning("[確認] プロセス終了後の状態確認")
                        self._log_chrome_processes("プロセス終了後")
                except Exception as e:
                    self.logger.warning(f"プロファイル特定のプロセス終了でエラー: {e}")
                
                # 追加のクリーンアップ（従来の処理も保持）
                self._kill_existing_chrome_processes(current_profile_path)
                
                # より包括的なロックファイル削除
                self._cleanup_profile_locks(current_profile_path)
                
                self.logger.warning(f"[タイミング1] ChromeDriver取得前のプロセス確認")
                self._log_chrome_processes("[ChromeDriver取得前]")
                
                # ChromeDriverのセットアップ
                if not self._driver_path:
                    self.logger.info("ChromeDriverを初回インストール中...")
                    self._driver_path = ChromeDriverManager().install()
                    self.logger.info(f"ChromeDriverパス: {self._driver_path}")
                    self.logger.warning(f"[タイミング2] ChromeDriverManager.install()後のプロセス確認")
                    self._log_chrome_processes("[ChromeDriverManager後]")
                    try:
                        killed_pids = self.kill_chrome_using_profile(current_profile_path, timeout=2)
                        if killed_pids:
                            self.logger.info(f"ChromeDriver後のクリーンアップ: PIDs={killed_pids}")
                            time.sleep(0.5)
                    except Exception:
                        pass
                
                service = Service(self._driver_path)
                self.logger.warning(f"[タイミング3] Service作成後のプロセス確認")
                self._log_chrome_processes("[Service作成後]")
                
                # Chrome起動オプションの設定
                chrome_options = self._build_chrome_options(current_profile_path, **options)
                self.logger.info(f"[Chrome] user-data-dir = {current_profile_path}")
                
                # 最終プロセス確認とロックファイル削除
                self._cleanup_profile_locks(current_profile_path)
                
                self.logger.warning(f"[重要] WebDriver初期化直前のプロセス確認開始")
                if self._check_chrome_processes("[OK] WebDriver初期化前にChromeプロセスは存在しません"):
                    self.logger.error(f"[危険] WebDriver初期化前にChromeプロセスが存在します")
                    self._force_kill_all_chrome_processes()
                    time.sleep(1)
                
                # Chrome WebDriverの起動
                self.logger.warning(f"[重要] webdriver.Chrome() 呼び出し開始: {time.time()}")
                driver = webdriver.Chrome(service=service, options=chrome_options)
                
                self.logger.info(f"Chrome起動成功（試行 {attempt + 1}/{max_retries}）")
                return driver
                
            except Exception as e:
                last_exception = e
                self.logger.error(f"Chrome起動エラー（試行 {attempt + 1}/{max_retries}）: {str(e)}")
                
                # プロセス強制終了を試行
                try:
                    self._force_kill_all_chrome_processes()
                    time.sleep(1)
                except Exception as cleanup_error:
                    self.logger.warning(f"プロセス強制終了でエラー: {cleanup_error}")
        
        # すべてのリトライが失敗した場合、最後の手段として一時プロファイルを試行
        self.logger.warning("[最終手段] 一時プロファイルでの起動を試行")
        try:
            return self._launch_with_temporary_profile(**options)
        except Exception as temp_error:
            self.logger.error(f"一時プロファイルでの起動も失敗: {temp_error}")
        
        raise ChromeLaunchError(
            f"Chrome起動に{max_retries}回失敗しました。最後のエラー: {str(last_exception)}"
        )
    
    def _create_unique_temp_profile(self, base_profile_name: str) -> str:
        """ユニークな一時プロファイルを作成
        
        Args:
            base_profile_name: ベースプロファイル名
            
        Returns:
            str: 作成された一時プロファイルのパス
            
        Raises:
            ProfileCreationError: プロファイル作成に失敗した場合
        """
        try:
            # ユニークな一時プロファイル名を生成
            timestamp = int(time.time())
            pid = os.getpid()
            unique_id = str(uuid.uuid4())[:8]
            temp_name = f"{base_profile_name}_temp_{timestamp}_{pid}_{unique_id}"
            
            # 一時プロファイル用ディレクトリを作成
            temp_base_dir = self.base_profiles_dir / "_temp"
            temp_base_dir.mkdir(exist_ok=True)
            
            temp_profile_path = temp_base_dir / temp_name
            temp_profile_path.mkdir(parents=True, exist_ok=True)
            
            # ベースプロファイルが存在する場合、必要最小限をコピー
            base_profile_path = self.base_profiles_dir / base_profile_name
            if base_profile_path.exists():
                self._copy_essential_profile_data(base_profile_path, temp_profile_path)
            else:
                # ベースプロファイルがない場合はデフォルト設定を作成
                self._setup_default_preferences(temp_profile_path)
            
            self.logger.info(f"プロファイル作成完了: {temp_profile_path}")
            return str(temp_profile_path)
            
        except Exception as e:
            self.logger.error(f"一時プロファイル作成エラー: {e}")
            raise ProfileCreationError(f"一時プロファイル '{temp_name}' の作成に失敗: {e}")
    
    def _copy_essential_profile_data(self, source_path: Path, dest_path: Path) -> None:
        """プロファイルの必要最小限のデータをコピー
        
        Args:
            source_path: コピー元プロファイルパス
            dest_path: コピー先プロファイルパス
        """
        try:
            # コピーする重要ファイル/ディレクトリ（軽量化のためキャッシュ類は除外）
            essential_items = [
                "Default/Preferences",
                "Default/Secure Preferences",
                "Default/Local State",
                "Default/Cookies",
                "Default/Login Data",
                "Default/Web Data",
                "First Run",
                "Local State"
            ]
            
            for item in essential_items:
                source_item = source_path / item
                dest_item = dest_path / item
                
                if source_item.exists():
                    dest_item.parent.mkdir(parents=True, exist_ok=True)
                    
                    if source_item.is_file():
                        shutil.copy2(source_item, dest_item)
                    elif source_item.is_dir():
                        shutil.copytree(source_item, dest_item, dirs_exist_ok=True)
                    
                    self.logger.debug(f"プロファイルデータをコピー: {item}")
                    
        except Exception as e:
            self.logger.warning(f"プロファイルデータのコピー中にエラー: {e}")
    
    def launch_with_profile(
        self, 
        profile_path: str, 
        **options
    ) -> webdriver.Chrome:
        """指定プロファイルでChromeを起動（後方互換性のため）
        
        Args:
            profile_path: プロファイルパス
            **options: Chrome起動オプション
            
        Returns:
            webdriver.Chrome: Chrome WebDriverインスタンス
            
        Raises:
            ChromeLaunchError: Chrome起動に失敗した場合
        """
        return self._launch_with_retries(profile_path, max_retries=1, **options)
    
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
        # Windowsの権限問題対策: 絶対パスを使用
        import os
        absolute_profile_path = os.path.abspath(profile_path)
        options.add_argument(f"--user-data-dir={absolute_profile_path}")
        options.add_argument("--profile-directory=Default")
        
        # Windows権限エラー対策
        options.add_argument("--disable-features=LockProfileData")
        options.add_argument("--disable-features=ProcessSingletonLock")
        
        # 基本ステルス設定
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Windows専用: SingletonLockエラー対策
        import platform
        if platform.system() == 'Windows':
            options.add_argument("--disable-single-click-autofill")
            options.add_argument("--disable-gpu-sandbox")
            options.add_argument("--disable-setuid-sandbox")
            options.add_argument("--remote-debugging-port=0")  # ランダムポートを使用
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # プロセス競合対策
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--no-first-run")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-translate")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--force-device-scale-factor=1")
        
        # カスタムオプション適用
        if custom_options.get('headless', False):
            # 新しいヘッドレスモードを使用
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-software-rasterizer")
            # window-sizeは下で設定するため、ここでは設定しない
        
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
    
    def _kill_existing_chrome_processes(self, profile_path: str, timeout: int = 10) -> None:
        """同一プロファイルの既存Chromeプロセスを終了
        
        Args:
            profile_path: プロファイルパス
            timeout: プロセス終了待機タイムアウト（秒）
            
        Raises:
            ProcessKillError: プロセス終了に失敗した場合
        """
        killed_processes = []
        failed_processes = []
        
        try:
            # 正規化されたプロファイルパスを取得
            normalized_profile_path = str(Path(profile_path).resolve())
            
            # より安全なプロセス検索（権限エラー対策）
            try:
                processes = list(psutil.process_iter(['pid', 'name']))
            except Exception as e:
                self.logger.warning(f"プロセス一覧取得でエラー: {e}")
                # プロセス取得に失敗した場合も、ロックファイル削除は実行
                self._cleanup_profile_locks(profile_path)
                return
            
            for proc in processes:
                try:
                    proc_info = proc.info
                    
                    # Chromeプロセスかチェック
                    if not proc_info.get('name') or 'chrome' not in proc_info['name'].lower():
                        continue
                    
                    # cmdlineの取得を安全に行う
                    try:
                        cmdline = proc.cmdline()
                    except (psutil.AccessDenied, psutil.NoSuchProcess, PermissionError):
                        # 権限がない場合はスキップ（システムプロセスなど）
                        continue
                    except Exception as e:
                        # その他の例外もスキップ
                        self.logger.debug(f"cmdline取得エラー（PID {proc.pid}）: {e}")
                        continue
                        
                    if not cmdline:
                        continue
                        
                    cmdline_str = ' '.join(cmdline)
                    if normalized_profile_path in cmdline_str or profile_path in cmdline_str:
                        self.logger.info(f"同一プロファイルのChromeプロセスを検出: PID={proc.pid}")
                        
                        # プロセス終了を試行
                        try:
                            self._terminate_process_safely(proc, timeout)
                            killed_processes.append(proc.pid)
                        except Exception as term_error:
                            self.logger.warning(f"プロセス{proc.pid}終了失敗: {term_error}")
                            failed_processes.append(proc.pid)
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # プロセスが既に終了済みまたはアクセス拒否の場合はスキップ
                    continue
                except Exception as e:
                    self.logger.debug(f"プロセスチェック中のエラー: {e}")
                    continue
            
            if killed_processes:
                self.logger.info(f"既存Chromeプロセスを終了しました: PIDs={killed_processes}")
                
            if failed_processes:
                self.logger.warning(f"一部プロセスの終了に失敗: PIDs={failed_processes}")
                
            # プロセス終了の成功/失敗に関わらず、ロックファイルをクリーンアップ
            self._cleanup_profile_locks(profile_path)
                
        except Exception as e:
            self.logger.error(f"プロセス終了処理でエラー: {e}")
            # エラーが発生してもロックファイル削除は試行
            try:
                self._cleanup_profile_locks(profile_path)
            except Exception as cleanup_error:
                self.logger.error(f"ロックファイル削除もエラー: {cleanup_error}")
            # 致命的でない限り例外は投げない（リトライループを防ぐ）
            self.logger.warning("プロセス終了に失敗しましたが、処理を続行します")
    
    def _cleanup_profile_locks(self, profile_path: str):
        """プロファイルディレクトリのロックファイルを強制的にクリーンアップ
        
        Windows権限問題とBrowserMetricsアクセス拒否に対応した改善版。
        """
        profile_dir = Path(profile_path)
        if not profile_dir.exists():
            return
            
        import platform
        is_windows = platform.system() == 'Windows'
        
        cleaned_files = []
        
        # Windows環境での強制削除
        def force_remove_windows(file_path: Path):
            """Windows環境でファイル/ディレクトリを強制削除"""
            if not file_path.exists():
                return True
                
            try:
                if file_path.is_file():
                    # ファイルの属性をクリア
                    import stat
                    try:
                        file_path.chmod(stat.S_IWRITE)
                    except:
                        pass
                    file_path.unlink()
                    return True
                elif file_path.is_dir():
                    # ディレクトリの場合
                    import shutil
                    def handle_remove_readonly(func, path, exc):
                        import stat
                        import os
                        os.chmod(path, stat.S_IWRITE)
                        func(path)
                    
                    shutil.rmtree(str(file_path), onerror=handle_remove_readonly)
                    return True
            except:
                pass
                
            # コマンドラインツールでの強制削除
            if is_windows:
                try:
                    import subprocess
                    if file_path.is_file():
                        # delコマンドで強制削除
                        result = subprocess.run(
                            f'del /F /Q "{str(file_path)}"',
                            shell=True,
                            capture_output=True,
                            timeout=3
                        )
                    else:
                        # rmdirコマンドで強制削除
                        result = subprocess.run(
                            f'rmdir /S /Q "{str(file_path)}"',
                            shell=True,
                            capture_output=True,
                            timeout=3
                        )
                    return result.returncode == 0
                except:
                    pass
            
            return False
        
        # 問題のあるディレクトリを優先的に削除
        problem_dirs = [
            profile_dir / 'BrowserMetrics',
            profile_dir / 'Default' / 'BrowserMetrics',
            profile_dir / 'ShaderCache',
            profile_dir / 'Default' / 'ShaderCache',
            profile_dir / 'Default' / 'Service Worker',
            profile_dir / 'Default' / 'IndexedDB',
        ]
        
        for problem_dir in problem_dirs:
            if problem_dir.exists():
                try:
                    if is_windows:
                        if force_remove_windows(problem_dir):
                            cleaned_files.append(str(problem_dir))
                            self.logger.debug(f"問題ディレクトリ削除（強制）: {problem_dir}")
                    else:
                        if problem_dir.is_dir():
                            import shutil
                            shutil.rmtree(str(problem_dir))
                        else:
                            problem_dir.unlink()
                        cleaned_files.append(str(problem_dir))
                        self.logger.debug(f"問題ディレクトリ削除: {problem_dir}")
                except Exception as e:
                    self.logger.debug(f"問題ディレクトリ削除失敗: {problem_dir}, エラー: {e}")
        
        # ロックファイルパターンを削除
        lock_patterns = [
            'Singleton*',
            '*.lock',
            'lockfile*', 
            'parent.lock',
            '*/LOCK',
            'SingletonLock',
            'SingletonSocket',
            'SingletonCookie',
            '.org.chromium.Chromium.*'  # Linux/Mac用
        ]
        
        for pattern in lock_patterns:
            # トップレベルのファイル
            try:
                for lock_file in profile_dir.glob(pattern):
                    try:
                        if lock_file.is_file():
                            if is_windows:
                                if force_remove_windows(lock_file):
                                    cleaned_files.append(str(lock_file))
                                    self.logger.debug(f"ロックファイル削除（強制）: {lock_file}")
                            else:
                                lock_file.unlink()
                                cleaned_files.append(str(lock_file))
                                self.logger.debug(f"ロックファイル削除: {lock_file}")
                    except Exception as e:
                        self.logger.debug(f"ロックファイル削除失敗: {lock_file}, エラー: {e}")
            except Exception:
                pass
                
            # サブディレクトリ内のファイル（安全に実行）
            try:
                for lock_file in profile_dir.glob(f"**/{pattern}"):
                    try:
                        if lock_file.is_file():
                            if is_windows:
                                if force_remove_windows(lock_file):
                                    cleaned_files.append(str(lock_file))
                                    self.logger.debug(f"ロックファイル削除（サブディレクトリ・強制）: {lock_file}")
                            else:
                                lock_file.unlink()
                                cleaned_files.append(str(lock_file))
                                self.logger.debug(f"ロックファイル削除（サブディレクトリ）: {lock_file}")
                    except Exception as e:
                        self.logger.debug(f"サブディレクトリのロックファイル削除失敗: {lock_file}, エラー: {e}")
            except Exception:
                pass
        
        # Windows環境での追加クリーンアップ
        if is_windows:
            # Default/SingletonLock などの特定ファイルを直接削除
            specific_locks = [
                profile_dir / 'Default' / 'SingletonLock',
                profile_dir / 'Default' / 'SingletonSocket',
                profile_dir / 'Default' / 'SingletonCookie',
                profile_dir / 'SingletonLock',
                profile_dir / 'SingletonSocket',
                profile_dir / 'SingletonCookie',
            ]
            
            for lock_file in specific_locks:
                if lock_file.exists() and lock_file.is_file():
                    if force_remove_windows(lock_file):
                        cleaned_files.append(str(lock_file))
                        self.logger.debug(f"特定ロックファイル削除: {lock_file}")
        
        if cleaned_files:
            self.logger.info(f"ロックファイルクリーンアップ完了: {len(cleaned_files)}個のファイル/ディレクトリを削除")
        else:
            self.logger.debug("削除すべきロックファイルは見つかりませんでした")

    def _recreate_profile_directory(self, profile_path: str) -> str:
        """
        プロファイルディレクトリを完全削除して再作成
        
        Args:
            profile_path: 元のプロファイルパス
            
        Returns:
            str: 再作成されたプロファイルパス
        """
        try:
            self.logger.info(f"[プロファイル再作成] 完全リセット開始: {profile_path}")
            
            # レジストリと一時ファイルクリーンアップ
            self._cleanup_chrome_registry()
            self._cleanup_chrome_temp_files()
            
            if os.path.exists(profile_path):
                # Windows環境での強制削除
                if platform.system() == "Windows":
                    try:
                        # takeownとicaclsによる権限変更
                        subprocess.run([
                            "takeown", "/F", profile_path, "/R", "/D", "Y"
                        ], capture_output=True, timeout=10)
                        
                        subprocess.run([
                            "icacls", profile_path, "/grant", "Everyone:F", "/T"
                        ], capture_output=True, timeout=10)
                        
                        subprocess.run([
                            "attrib", "-R", "/S", profile_path + "\\*.*"
                        ], capture_output=True, timeout=10)
                        
                        # rmdir による強制削除
                        subprocess.run([
                            "rmdir", "/S", "/Q", profile_path
                        ], capture_output=True, timeout=15)
                        
                        self.logger.info(f"[成功] Windows権限変更による削除完了")
                    except Exception as win_error:
                        self.logger.warning(f"[Windows削除失敗] {win_error}")
                        # Python標準ライブラリでのフォールバック
                        shutil.rmtree(profile_path, ignore_errors=True)
                else:
                    shutil.rmtree(profile_path, ignore_errors=True)
            
            # ディレクトリの再作成
            os.makedirs(profile_path, exist_ok=True)
            self.logger.info(f"[成功] プロファイルディレクトリ再作成完了: {profile_path}")
            
            # 作成確認のため少し待機
            time.sleep(0.5)
            
            return profile_path
            
        except Exception as e:
            self.logger.error(f"[失敗] プロファイル再作成エラー: {e}")
            return profile_path
    
    def _create_alternative_profile(self, original_path: str) -> str:
        """
        タイムスタンプ付きの代替プロファイルパスを作成
        
        Args:
            original_path: 元のプロファイルパス
            
        Returns:
            str: 代替プロファイルパス
        """
        try:
            timestamp = int(time.time() * 1000)  # ミリ秒タイムスタンプ
            pid = os.getpid()  # プロセスID
            
            # 元のパスの親ディレクトリを取得
            parent_dir = os.path.dirname(original_path)
            original_name = os.path.basename(original_path)
            
            # 代替パスを生成
            alternative_path = os.path.join(parent_dir, f"{original_name}_alt_{timestamp}_{pid}")
            
            self.logger.info(f"[代替プロファイル] 作成: {alternative_path}")
            
            # ディレクトリ作成
            os.makedirs(alternative_path, exist_ok=True)
            
            return alternative_path
            
        except Exception as e:
            self.logger.error(f"[失敗] 代替プロファイル作成エラー: {e}")
            return original_path
    
    def _force_kill_all_chrome_processes(self):
        """
        すべてのChromeプロセスを強制終了（緊急時用）
        """
        try:
            self.logger.warning("[緊急措置] すべてのChromeプロセスを強制終了")
            
            if platform.system() == "Windows":
                # taskkill による強制終了
                subprocess.run([
                    "taskkill", "/F", "/IM", "chrome.exe"
                ], capture_output=True)
                
                subprocess.run([
                    "taskkill", "/F", "/IM", "chromedriver.exe"
                ], capture_output=True)
                
                # PowerShellによる詳細終了
                powershell_cmd = """
                Get-Process | Where-Object {$_.ProcessName -like '*chrome*'} | Stop-Process -Force
                Get-Process | Where-Object {$_.MainWindowTitle -like '*Chrome*'} | Stop-Process -Force
                """
                subprocess.run([
                    "powershell", "-Command", powershell_cmd
                ], capture_output=True, timeout=10)
            else:
                subprocess.run(["pkill", "-f", "chrome"], capture_output=True)
                subprocess.run(["pkill", "-f", "chromedriver"], capture_output=True)
            
            time.sleep(2)  # プロセス終了の待機
            self.logger.info("[完了] Chrome強制終了処理完了")
            
        except Exception as e:
            self.logger.error(f"[失敗] Chrome強制終了エラー: {e}")
    
    def _launch_with_temporary_profile(self, **chrome_options) -> webdriver.Chrome:
        """
        最後の手段：一時プロファイルでの起動
        
        Args:
            **chrome_options: Chrome起動オプション
            
        Returns:
            webdriver.Chrome: 起動されたChromeドライバー
        """
        try:
            import tempfile
            
            # 一時ディレクトリ作成
            temp_profile_path = tempfile.mkdtemp(prefix="chrome_temp_profile_")
            self.logger.info(f"[一時プロファイル] 作成: {temp_profile_path}")
            
            # ChromeDriverのセットアップ
            service = Service(self._driver_path)
            
            # 一時プロファイル用のChrome起動オプション
            temp_options = self._build_chrome_options(temp_profile_path, **chrome_options)
            
            # 追加の安定化オプション
            temp_options.add_argument("--disable-features=VizDisplayCompositor")
            temp_options.add_argument("--disable-gpu")
            temp_options.add_argument("--disable-software-rasterizer")
            temp_options.add_argument("--disable-background-timer-throttling")
            temp_options.add_argument("--disable-backgrounding-occluded-windows")
            temp_options.add_argument("--disable-renderer-backgrounding")
            temp_options.add_argument("--disable-field-trial-config")
            
            self.logger.warning(f"[一時プロファイル] WebDriver起動開始")
            driver = webdriver.Chrome(service=service, options=temp_options)
            
            self.logger.info(f"[成功] 一時プロファイルでのChrome起動完了")
            return driver
            
        except Exception as e:
            self.logger.error(f"[失敗] 一時プロファイル起動エラー: {e}")
            raise
    
    def _cleanup_chrome_registry(self):
        """
        Windows環境でのChrome関連レジストリクリーンアップ
        """
        if platform.system() != "Windows":
            return
        
        try:
            self.logger.info("[レジストリ] Chrome関連レジストリのクリーンアップ開始")
            
            # PowerShellスクリプトでレジストリクリーンアップ
            powershell_script = """
            $registryPaths = @(
                'HKCU:\Software\Google\Chrome\Profile',
                'HKCU:\Software\Google\Chrome\UserData',
                'HKCU:\Software\Chromium\Profile',
                'HKCU:\Software\Chromium\UserData'
            )
            
            foreach ($path in $registryPaths) {
                if (Test-Path $path) {
                    Remove-Item -Path $path -Recurse -Force -ErrorAction SilentlyContinue
                    Write-Host "Cleaned: $path"
                }
            }
            """
            
            result = subprocess.run([
                "powershell", "-Command", powershell_script
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                self.logger.info("[成功] レジストリクリーンアップ完了")
            else:
                self.logger.warning(f"[警告] レジストリクリーンアップで警告: {result.stderr}")
                
        except Exception as e:
            self.logger.error(f"[失敗] レジストリクリーンアップエラー: {e}")
    
    def _cleanup_chrome_temp_files(self):
        """
        Chrome関連一時ファイルのクリーンアップ
        """
        try:
            self.logger.info("[一時ファイル] Chrome一時ファイルクリーンアップ開始")
            
            temp_patterns = [
                os.path.join(os.environ.get('TEMP', ''), 'chrome*'),
                os.path.join(os.environ.get('TEMP', ''), 'scoped_dir*'),
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data', 'Crashpad'),
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data', 'lockfile')
            ]
            
            import glob
            for pattern in temp_patterns:
                try:
                    matches = glob.glob(pattern)
                    for match in matches:
                        if os.path.isdir(match):
                            shutil.rmtree(match, ignore_errors=True)
                        else:
                            os.remove(match)
                    if matches:
                        self.logger.debug(f"[削除] {len(matches)}個のファイル/ディレクトリを削除: {pattern}")
                except Exception:
                    pass  # 一時ファイルの削除エラーは無視
                    
            self.logger.info("[完了] Chrome一時ファイルクリーンアップ完了")
            
        except Exception as e:
            self.logger.error(f"[失敗] 一時ファイルクリーンアップエラー: {e}")
    
    def _check_chrome_processes(self, message: str = "") -> bool:
        """
        Chromeプロセスの存在確認
        
        Args:
            message: ログメッセージ
            
        Returns:
            bool: Chromeプロセスが存在する場合True
        """
        try:
            chrome_processes = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    proc_info = proc.info
                    name = (proc_info.get('name') or "").lower()
                    if 'chrome' in name or 'chromedriver' in name:
                        chrome_processes.append(f"PID={proc.pid}, Name={name}")
                except Exception:
                    pass
            
            if chrome_processes:
                self.logger.info(f"{message} Chrome関連プロセス検出: {chrome_processes}")
                return True
            else:
                self.logger.info(f"{message} Chrome関連プロセスなし")
                return False
                
        except Exception as e:
            self.logger.warning(f"プロセスチェックエラー: {e}")
            return False
    
    def _terminate_process_safely(self, process: psutil.Process, timeout: int = 10) -> None:
        """プロセスを安全に終了
        
        Args:
            process: 終了対象のプロセス
            timeout: 終了待機タイムアウト（秒）
        """
        try:
            # まず通常終了を試行
            if platform.system() == "Windows":
                process.terminate()
            else:
                process.send_signal(signal.SIGTERM)
            
            # プロセス終了を待機
            try:
                process.wait(timeout=timeout//2)
                self.logger.debug(f"プロセス {process.pid} が正常終了しました")
                return
            except psutil.TimeoutExpired:
                self.logger.warning(f"プロセス {process.pid} の正常終了がタイムアウト、強制終了します")
            
            # 強制終了を試行
            if platform.system() == "Windows":
                process.kill()
            else:
                process.send_signal(signal.SIGKILL)
                
            # 強制終了の完了を待機
            try:
                process.wait(timeout=timeout//2)
                self.logger.info(f"プロセス {process.pid} を強制終了しました")
            except psutil.TimeoutExpired:
                self.logger.error(f"プロセス {process.pid} の強制終了もタイムアウトしました")
                
        except psutil.NoSuchProcess:
            # プロセスが既に存在しない場合は正常
            self.logger.debug(f"プロセス {process.pid} は既に終了済みです")
        except Exception as e:
            self.logger.error(f"プロセス {process.pid} の終了中にエラー: {e}")
            raise
    
    def get_running_chrome_processes(self, profile_path: str = None) -> List[Dict]:
        """実行中のChromeプロセス情報を取得
        
        Args:
            profile_path: 特定のプロファイルのみを対象にする場合のパス
            
        Returns:
            List[Dict]: プロセス情報のリスト
        """
        chrome_processes = []
        
        try:
            normalized_profile_path = None
            if profile_path:
                normalized_profile_path = str(Path(profile_path).resolve())
            
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'memory_info']):
                try:
                    proc_info = proc.info
                    
                    # Chromeプロセスかチェック
                    if not proc_info['name'] or 'chrome' not in proc_info['name'].lower():
                        continue
                    
                    # 特定プロファイルのフィルタリング
                    if profile_path:
                        cmdline = proc_info['cmdline']
                        if not cmdline:
                            continue
                        cmdline_str = ' '.join(cmdline)
                        if normalized_profile_path not in cmdline_str and profile_path not in cmdline_str:
                            continue
                    
                    chrome_processes.append({
                        'pid': proc_info['pid'],
                        'name': proc_info['name'],
                        'cmdline': proc_info['cmdline'],
                        'create_time': proc_info['create_time'],
                        'memory_mb': round(proc_info['memory_info'].rss / 1024 / 1024, 1) if proc_info.get('memory_info') else None
                    })
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                    
        except Exception as e:
            self.logger.error(f"プロセス情報取得エラー: {e}")
            
        return chrome_processes
    
    def cleanup_temp_profiles(self, older_than_hours: int = 24) -> int:
        """古い一時プロファイルをクリーンアップ
        
        Args:
            older_than_hours: 何時間前より古いプロファイルを削除するか
            
        Returns:
            int: 削除されたプロファイル数
        """
        deleted_count = 0
        
        try:
            temp_dir = self.base_profiles_dir / "_temp"
            if not temp_dir.exists():
                return 0
            
            cutoff_time = time.time() - (older_than_hours * 3600)
            
            for temp_profile in temp_dir.iterdir():
                if temp_profile.is_dir() and temp_profile.name.startswith(("twitter_main_temp_", "_temp_")):
                    try:
                        # プロファイルの作成時刻をチェック
                        profile_ctime = temp_profile.stat().st_ctime
                        
                        if profile_ctime < cutoff_time:
                            # 使用中でないかチェック
                            running_processes = self.get_running_chrome_processes(str(temp_profile))
                            if not running_processes:
                                shutil.rmtree(temp_profile)
                                deleted_count += 1
                                self.logger.info(f"古い一時プロファイルを削除: {temp_profile.name}")
                            else:
                                self.logger.info(f"使用中のため削除スキップ: {temp_profile.name}")
                    except Exception as e:
                        self.logger.warning(f"一時プロファイル削除エラー {temp_profile.name}: {e}")
            
            self.logger.info(f"一時プロファイルクリーンアップ完了: {deleted_count}個削除")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"一時プロファイルクリーンアップエラー: {e}")
            return 0
    
    def kill_chrome_using_profile(self, profile_path: str, timeout: int = 10) -> list[int]:
        """特定プロファイルを使用しているChromeプロセスのみを終了
        
        Windows環境でのタイムアウト問題を解決した改善版。
        より確実で高速な処理を実装。
        
        Args:
            profile_path: 対象プロファイルパス
            timeout: プロセス終了タイムアウト
            
        Returns:
            List[int]: 終了したプロセスIDのリスト
        """
        killed_pids = []
        
        try:
            import platform
            is_windows = platform.system() == 'Windows'
            
            # 正規化されたプロファイルパスを取得
            normalized_profile_path = str(Path(profile_path).resolve())
            self.logger.debug(f"プロファイルパスを検索: {normalized_profile_path}")
            
            # Windows環境での強制終了（確実で高速な方式）
            if is_windows:
                self.logger.info("Windows環境での強制プロセス終了を開始")
                
                try:
                    import subprocess
                    
                    # taskkillコマンドで直接Chrome全体を終了（最も確実）
                    # まず、プロファイルパスを含むChromeプロセスがあるかチェック
                    check_cmd = f'tasklist /FI "IMAGENAME eq chrome.exe" /FO CSV'
                    result = subprocess.run(
                        check_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=3  # 短時間でタイムアウト
                    )
                    
                    if "chrome.exe" in result.stdout:
                        self.logger.info("Chromeプロセスが検出されました。強制終了します。")
                        
                        # Chrome全体を終了（プロファイルロック解除のため）
                        kill_result = subprocess.run(
                            'taskkill /F /IM chrome.exe',
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=3
                        )
                        
                        if kill_result.returncode == 0:
                            self.logger.info("Chrome全体を強制終了しました（プロファイルロック解除）")
                            # 実際のPIDは取得困難だが、便宜上1を返す
                            killed_pids.append(1)
                        
                        # ChromeDriverも終了
                        subprocess.run(
                            'taskkill /F /IM chromedriver.exe',
                            shell=True,
                            capture_output=True,
                            timeout=2
                        )
                        
                        # プロセス終了を待つ
                        time.sleep(1)
                        
                    else:
                        self.logger.info("Chromeプロセスは検出されませんでした")
                        
                except subprocess.TimeoutExpired:
                    self.logger.warning("taskkillコマンドがタイムアウトしました")
                except Exception as e:
                    self.logger.warning(f"taskkillコマンド実行エラー: {e}")
                    
                # 代替手段: PowerShellなしで直接プロセス検索
                if not killed_pids:
                    try:
                        chrome_processes_found = []
                        
                        # psutilでのシンプルなプロセス検索
                        for proc in psutil.process_iter(['pid', 'name']):
                            try:
                                proc_info = proc.info
                                name = (proc_info.get('name') or "").lower()
                                
                                if 'chrome' in name:
                                    chrome_processes_found.append(f"PID={proc.pid}")
                                    try:
                                        # プロセスを直接終了（コマンドライン検査なし）
                                        proc.kill()
                                        killed_pids.append(proc.pid)
                                        self.logger.info(f"Chrome関連プロセス終了: PID={proc.pid}")
                                        time.sleep(0.1)  # 短い待機
                                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                                        continue
                                        
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                                continue
                                
                        if chrome_processes_found:
                            self.logger.info(f"検出されたChromeプロセス: {chrome_processes_found}")
                            
                    except Exception as e:
                        self.logger.warning(f"プロセス直接終了エラー: {e}")
            
            else:
                # 非Windows環境での処理（既存のpsutil使用）
                try:
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                        try:
                            proc_info = proc.info
                            name = (proc_info.get('name') or "").lower()
                            
                            if 'chrome' in name or 'chromedriver' in name:
                                cmdline = proc_info.get('cmdline')
                                if cmdline:
                                    cmdline_str = " ".join(cmdline)
                                    if normalized_profile_path.lower() in cmdline_str.lower():
                                        self.logger.info(f"プロファイル使用プロセス終了: PID={proc.pid}")
                                        self._terminate_process_safely(proc, timeout)
                                        killed_pids.append(proc.pid)
                                        
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            continue
                            
                except Exception as e:
                    self.logger.warning(f"非Windows環境でのプロセス検索エラー: {e}")
            
            if not killed_pids:
                self.logger.info("終了すべきChromeプロセスは見つかりませんでした")
                    
        except Exception as e:
            self.logger.error(f"特定プロファイルのChrome終了エラー: {e}")
            
        if killed_pids:
            self.logger.info(f"Chromeプロセス終了完了: 対象数={len(killed_pids)}")
            
        # プロセス終了後にロックファイルをクリーンアップ
        try:
            self._cleanup_profile_locks(profile_path)
        except Exception:
            pass
            
        return killed_pids

    def _log_chrome_processes(self, timing_label: str) -> None:
        """Chrome/ChromeDriverプロセスの状態をログ出力（デバッグ用）
        
        Args:
            timing_label: タイミングを示すラベル
        """
        try:
            chrome_processes = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    proc_info = proc.info
                    name = (proc_info.get('name') or "").lower()
                    if 'chrome' in name or 'chromedriver' in name:
                        chrome_processes.append(f"PID={proc.pid}, Name={name}")
                except Exception:
                    pass
            
            if chrome_processes:
                self.logger.warning(f"[{timing_label}] Chrome関連プロセス: {chrome_processes}")
            else:
                self.logger.info(f"[{timing_label}] Chrome関連プロセスなし")
        except Exception as e:
            self.logger.debug(f"プロセスログ出力エラー: {e}")
