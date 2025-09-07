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
            # 既存の同一プロファイルのChromeプロセスを終了
            self._kill_existing_chrome_processes(profile_path)
            
            # ロックファイルを事前にクリーンアップ
            self._cleanup_profile_locks(profile_path)
            
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
            
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
                try:
                    proc_info = proc.info
                    
                    # Chromeプロセスかチェック
                    if not proc_info['name'] or 'chrome' not in proc_info['name'].lower():
                        continue
                        
                    # コマンドラインに同じプロファイルパスが含まれているかチェック
                    cmdline = proc_info['cmdline']
                    if not cmdline:
                        continue
                        
                    cmdline_str = ' '.join(cmdline)
                    if normalized_profile_path in cmdline_str or profile_path in cmdline_str:
                        self.logger.info(f"同一プロファイルのChromeプロセスを検出: PID={proc.pid}")
                        
                        # プロセス終了を試行
                        self._terminate_process_safely(proc, timeout)
                        killed_processes.append(proc.pid)
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # プロセスが既に終了済みまたはアクセス拒否の場合はスキップ
                    continue
                except Exception as e:
                    self.logger.warning(f"プロセスチェック中のエラー: {e}")
                    failed_processes.append(str(e))
            
            if killed_processes:
                self.logger.info(f"既存Chromeプロセスを終了しました: PIDs={killed_processes}")
                # プロセス終了後にロックファイルをクリーンアップ
                self._cleanup_profile_locks(profile_path)
                
            if failed_processes:
                self.logger.warning(f"一部プロセスの終了に失敗: {failed_processes}")
                
        except Exception as e:
            self.logger.error(f"プロセス終了処理でエラー: {e}")
            raise ProcessKillError(f"既存プロセスの終了に失敗: {e}")
    
    def _cleanup_profile_locks(self, profile_path: str) -> None:
        """プロファイルのロックファイルをクリーンアップ
        
        Args:
            profile_path: プロファイルパス
        """
        try:
            import time
            # プロセス終了後の安定化を待つ
            time.sleep(1)
            
            profile_dir = Path(profile_path)
            if not profile_dir.exists():
                return
            
            # 削除対象のロックファイル（拡張版）
            lock_files = [
                "SingletonLock",
                "SingletonCookie",
                "SingletonSocket",
                "lockfile",
                "parent.lock",
                "data_reduction_proxy_leveldb/LOCK",
                "shared_proto_db/LOCK",
                "optimization_guide_model_store/LOCK",
            ]
            
            # ルートディレクトリのロックファイル削除
            for lock_file in lock_files:
                lock_path = profile_dir / lock_file
                if lock_path.exists():
                    try:
                        # Windowsの場合、読み取り専用属性を解除
                        if lock_path.is_file():
                            import stat
                            import os
                            os.chmod(str(lock_path), stat.S_IWRITE)
                        lock_path.unlink()
                        self.logger.debug(f"ロックファイル削除: {lock_path}")
                    except Exception as e:
                        self.logger.warning(f"ロックファイル削除失敗 {lock_path}: {e}")
                        
            # Defaultディレクトリ内のロックファイルもチェック
            default_dir = profile_dir / "Default"
            if default_dir.exists():
                for lock_file in lock_files:
                    lock_path = default_dir / lock_file
                    if lock_path.exists():
                        try:
                            # Windowsの場合、読み取り専用属性を解除
                            if lock_path.is_file():
                                import stat
                                import os
                                os.chmod(str(lock_path), stat.S_IWRITE)
                            lock_path.unlink()
                            self.logger.debug(f"ロックファイル削除: {lock_path}")
                        except Exception as e:
                            self.logger.warning(f"ロックファイル削除失敗 {lock_path}: {e}")
                            
        except Exception as e:
            self.logger.warning(f"ロックファイルクリーンアップエラー: {e}")
    
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