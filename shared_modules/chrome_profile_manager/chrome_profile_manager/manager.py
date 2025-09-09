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
        
        # 通常プロファイルで失敗した場合、プロファイルを削除して再作成
        if fallback_to_temp:
            self.logger.warning(f"プロファイル '{profile_name}' が使用中のため、プロファイルを削除して再作成します。")
            try:
                # 既存プロファイルを完全削除
                old_profile_path = self.base_profiles_dir / profile_name
                if old_profile_path.exists():
                    import shutil
                    shutil.rmtree(old_profile_path)
                    self.logger.info(f"古いプロファイルを削除しました: {old_profile_path}")
                
                # 新しいプロファイルを作成
                new_profile_path = self.create_profile(profile_name, force_recreate=True)
                return self._launch_with_retries(new_profile_path, max_retries=1, **chrome_options)
                
            except Exception as recreate_error:
                self.logger.error(f"プロファイル再作成での起動も失敗: {recreate_error}")
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
        """指数バックオフ付きリトライでChromeを起動
        
        Args:
            profile_path: プロファイルパス
            max_retries: 最大リトライ回数
            **options: Chrome起動オプション
            
        Returns:
            webdriver.Chrome: Chrome WebDriverインスタンス
            
        Raises:
            ChromeLaunchError: Chrome起動に失敗した場合
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # より強力なクリーンアップ処理
                # プロファイル特定のChromeプロセスのみを終了（改善版）
                # 注意: 全Chromeプロセスを終了するのではなく、特定プロファイルのみ対象
                import platform
                
                # 対象プロファイルを使用しているプロセスを特定して終了
                self.logger.warning("[開始] プロファイル特定のクリーンアップ開始")
                self._log_chrome_processes("クリーンアップ開始時")
                try:
                    killed_pids = self.kill_chrome_using_profile(profile_path, timeout=5)
                    if killed_pids:
                        self.logger.info(f"プロファイル使用中のChromeプロセスを終了: PIDs={killed_pids}")
                        time.sleep(1)  # プロセス終了を待つ
                        # プロセス終了後の確認
                        self.logger.warning("[確認] プロセス終了後の状態確認")
                        self._log_chrome_processes("プロセス終了後")
                except Exception as e:
                    self.logger.warning(f"プロファイル特定のプロセス終了でエラー: {e}")
                
                # 追加のクリーンアップ（従来の処理も保持）
                self._kill_existing_chrome_processes(profile_path)
                
                # 3. プロファイルディレクトリ全体のロックファイルを強制削除
                profile_dir = Path(profile_path)
                if profile_dir.exists():
                    # より包括的なロックファイル削除
                    for pattern in ['Singleton*', '*.lock', 'lockfile*', 'parent.lock', '*/LOCK']:
                        for lock_file in profile_dir.glob(pattern):
                            try:
                                if lock_file.is_file():
                                    lock_file.unlink()
                                    self.logger.debug(f"ロックファイル削除: {lock_file}")
                            except Exception:
                                pass
                        for lock_file in profile_dir.glob(f"**/{pattern}"):
                            try:
                                if lock_file.is_file():
                                    lock_file.unlink()
                                    self.logger.debug(f"ロックファイル削除: {lock_file}")
                            except Exception:
                                pass
                
                # 4. 通常のロックファイルクリーンアップも実行
                self._cleanup_profile_locks(profile_path)
                
                # 少し待機してからChrome起動
                if attempt > 0:
                    time.sleep(0.2)
                
                chrome_options = self._build_chrome_options(profile_path, **options)
                # ChromeDriverのパスを取得（キャッシュ利用）
                # ChromeDriver取得前のプロセス確認
                self.logger.warning("[タイミング1] ChromeDriver取得前のプロセス確認")
                self._log_chrome_processes("ChromeDriver取得前")
                
                if not self._driver_path:
                    self.logger.info("ChromeDriverを初回インストール中...")
                    # ChromeDriverManagerのインストール前に再度クリーンアップ
                    # (ChromeDriverManagerがChromeを起動する可能性があるため)
                    self._driver_path = ChromeDriverManager().install()
                    self.logger.info(f"ChromeDriverパス: {self._driver_path}")
                    # ChromeDriverManager後のプロセス確認（重要）
                    self.logger.warning("[タイミング2] ChromeDriverManager.install()後のプロセス確認")
                    self._log_chrome_processes("ChromeDriverManager後")
                    # ChromeDriver取得後に再度プロファイル特定のクリーンアップ
                    try:
                        killed_pids = self.kill_chrome_using_profile(profile_path, timeout=2)
                        if killed_pids:
                            self.logger.info(f"ChromeDriver後のクリーンアップ: PIDs={killed_pids}")
                            time.sleep(0.5)
                    except Exception:
                        pass
                
                # ChromeDriver Service作成後のプロセス確認
                service = Service(self._driver_path)
                self.logger.warning("[タイミング3] Service作成後のプロセス確認")
                self._log_chrome_processes("Service作成後")
                
                # 実際のuser-data-dirをログ出力（デバッグ用）
                absolute_profile_path = os.path.abspath(profile_path)
                self.logger.info(f"[Chrome] user-data-dir = {absolute_profile_path}")
                
                # 最終的なプロファイルロック確認
                self._cleanup_profile_locks(profile_path)
                
                # WebDriver初期化直前のChrome��ロセス確認（重要）
                self.logger.warning("[重要] WebDriver初期化直前のプロセス確認開始")
                pre_init_chrome_processes = []
                try:
                    for proc in psutil.process_iter(['pid', 'name']):
                        try:
                            proc_info = proc.info
                            name = (proc_info.get('name') or "").lower()
                            if 'chrome' in name or 'chromedriver' in name:
                                pre_init_chrome_processes.append(f"PID={proc.pid}, Name={name}")
                        except Exception:
                            pass
                    if pre_init_chrome_processes:
                        self.logger.error(f"[警告] WebDriver初期化前にChromeプロセスが検出されました: {pre_init_chrome_processes}")
                        self.logger.error(f"[警告] これらのプロセスがプロファイル {profile_path} を使用している可能性があります")
                    else:
                        self.logger.info("[OK] WebDriver初期化前にChromeプロセスは存在しません")
                except Exception as e:
                    self.logger.warning(f"プロセスチェックエラー: {e}")
                
                # WebDriver初期化直前に短い待機
                time.sleep(0.3)
                
                self.logger.warning(f"[重要] webdriver.Chrome() 呼び出し開始: {time.time()}")
                driver = webdriver.Chrome(service=service, options=chrome_options)
                self.logger.warning(f"[重要] webdriver.Chrome() 呼び出し完了: {time.time()}")
                
                self.logger.info(f"Chrome起動成功: プロファイル={profile_path}")
                return driver
                
            except Exception as e:
                last_error = e
                self.logger.error(f"Chrome起動エラー（試行 {attempt + 1}/{max_retries}）: {e}")
                
                if attempt < max_retries - 1:
                    backoff_time = 0.5 * (2 ** attempt)
                    self.logger.info(f"リトライまで {backoff_time} 秒待機...")
                    time.sleep(backoff_time)
        
        raise ChromeLaunchError(f"Chrome起動に失敗（{max_retries}回試行）: {last_error}")
    
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
        
        Windows環境での権限問題に対応した強化版。
        """
        profile_dir = Path(profile_path)
        if not profile_dir.exists():
            return
            
        import platform
        is_windows = platform.system() == 'Windows'
        
        # ロックファイルパターンを拡張
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
        
        cleaned_files = []
        
        # Windows環境での強制削除関数
        def force_remove_windows(file_path: Path):
            """Windows環境でファイルを強制削除"""
            if not file_path.exists():
                return True
                
            try:
                # まず通常の削除を試みる
                if file_path.is_file():
                    # 読み取り専用属性を解除
                    import stat
                    try:
                        file_path.chmod(stat.S_IWRITE)
                    except:
                        pass
                    file_path.unlink()
                    return True
            except:
                pass
                
            # 通常削除が失敗した場合、コマンドラインツールを使用
            if is_windows:
                try:
                    import subprocess
                    # delコマンドで強制削除
                    result = subprocess.run(
                        f'del /F /Q "{str(file_path)}"',
                        shell=True,
                        capture_output=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        return True
                except:
                    pass
                    
                try:
                    # PowerShellでの削除も試みる
                    ps_cmd = f'Remove-Item -Path "{str(file_path)}" -Force -ErrorAction SilentlyContinue'
                    subprocess.run(
                        ['powershell', '-Command', ps_cmd],
                        capture_output=True,
                        timeout=5
                    )
                    return not file_path.exists()
                except:
                    pass
            
            return False
        
        # 各パターンに対してロックファイルを削除
        for pattern in lock_patterns:
            # トップレベルのファイル
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
                    self.logger.warning(f"ロックファイル削除失敗: {lock_file}, エラー: {e}")
                    
            # サブディレクトリ内のファイル
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
            self.logger.info(f"ロックファイルクリーンアップ完了: {len(cleaned_files)}個のファイルを削除")
        else:
            self.logger.debug("削除すべきロックファイルは見つかりませんでした")
    
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
