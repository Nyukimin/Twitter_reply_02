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

COOKIE_FILE = "cookie/twitter_cookies_01.pkl"

# WebDriverインスタンスを保持するグローバル変数
_driver: webdriver.Chrome | None = None
_driver_process_count = 0  # WebDriverの起動回数をカウント
_memory_monitor_enabled = True  # メモリ監視の有効/無効フラグ

# Profile認証用のグローバル変数
_auth_manager = None

def _get_auth_manager():
    """認証マネージャーの取得（遅延初期化）"""
    global _auth_manager
    if _auth_manager is None:
        from .auth.twitter_profile_auth import TwitterProfileAuth
        from .config import PROFILES_DIR
        _auth_manager = TwitterProfileAuth(PROFILES_DIR)
    return _auth_manager

def get_driver(headless: bool = True) -> webdriver.Chrome:
    """
    WebDriverの取得（既存関数の互換性維持）
    """
    return setup_driver(headless=headless)

def check_memory_usage():
    """
    現在のメモリ使用量を確認し、ログに記録します。
    """
    if not _memory_monitor_enabled:
        return
    
    try:
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        logging.info(f"現在のメモリ使用量: {memory_mb:.1f} MB")
        
        # 500MB以上の場合は警告
        if memory_mb > 500:
            logging.warning(f"メモリ使用量が高くなっています: {memory_mb:.1f} MB")
            
        return memory_mb
    except Exception as e:
        logging.warning(f"メモリ使用量の確認中にエラー: {e}")
        return None

def force_restart_driver():
    """強制再起動（Profile版）"""
    auth_manager = _get_auth_manager()
    auth_manager.close_driver()
    from .config import TWITTER_PROFILE_NAME
    profile_name = TWITTER_PROFILE_NAME
    return auth_manager.get_authenticated_driver(
        profile_name=profile_name,
        force_recreate=True
    )

def close_driver():
    """
    WebDriverの終了（既存関数の互換性維持）
    """
    auth_manager = _get_auth_manager()
    auth_manager.close_driver()

def setup_driver(headless: bool = True) -> webdriver.Chrome:
    """
    WebDriverのセットアップ（既存関数の互換性維持）
    内部実装をProfile認証に変更
    """
    auth_manager = _get_auth_manager()
    from .config import TWITTER_PROFILE_NAME
    profile_name = TWITTER_PROFILE_NAME
    
    try:
        return auth_manager.get_authenticated_driver(
            profile_name=profile_name,
            headless=headless
        )
    except Exception as e:
        logging.error(f"setup_driver failed: {e}")
        raise # ループが正常に終了した場合（通常は起こらない）

def get_cookie(driver: webdriver.Chrome):
    """
    指定されたURLにアクセスし、ユーザーがログインを完了するのを待ってから、
    Cookieをファイルに保存します。
    """
    try:
        # ログインページにアクセス
        driver.get(LOGIN_URL)
        logging.info(f"{LOGIN_URL} にアクセスしました。ログインを完了してください...")

        # ユーザーが手動でログインし、ホームページにリダイレクトされるのを待つ
        # タイムアウトを長めに設定 (例: 5分)
        WebDriverWait(driver, 300).until(
            EC.url_contains("x.com/home")
        )
        
        logging.info("ホームページへのリダイレクトを検出しました。Cookieを保存します。")
        
        # Cookieを保存
        cookies = driver.get_cookies()
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(cookies, f)
            
        logging.info(f"Cookieを {COOKIE_FILE} に保存しました。")

    except TimeoutException:
        logging.error("ログイン待機中にタイムアウトしました。時間内にログインが完了しなかった可能性があります。")
    except Exception as e:
        logging.error(f"Cookieの保存中にエラーが発生しました: {e}")
        raise e
        
    return None # ループが正常に終了した場合（通常は起こらない） 