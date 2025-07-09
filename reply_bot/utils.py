import logging
import pickle
import os
import time
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

def get_driver(headless: bool = True) -> webdriver.Chrome:
    """
    シングルトンパターンのように動作し、WebDriverインスタンスを一度だけ初期化して返します。
    2回目以降の呼び出しでは、既存のインスタンスを返します。
    """
    global _driver
    if _driver is None:
        options = Options()
        if headless:
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')

        try:
            service = Service(ChromeDriverManager().install())
            _driver = webdriver.Chrome(service=service, options=options)
            logging.info("新しいWebDriverインスタンスを初期化しました。")
            
            # Cookieを読み込んでログイン
            if not os.path.exists(COOKIE_FILE):
                logging.error(f"Cookieファイル {COOKIE_FILE} が見つかりません。")
                logging.error("最初に 'python -m reply_bot.get_cookie' を実行して、ログインとCookieの保存を完了させてください。")
                close_driver()
                raise FileNotFoundError(f"{COOKIE_FILE} not found.")

            try:
                with open(COOKIE_FILE, "rb") as f:
                    cookies = pickle.load(f)
                
                # Cookieをセットするために、一度ドメインにアクセス
                _driver.get("https://x.com/") 
                
                for cookie in cookies:
                    if 'expiry' in cookie:
                        # 'expiry' が存在し、浮動小数点数の場合は整数に変換
                        cookie['expiry'] = int(cookie['expiry'])
                    _driver.add_cookie(cookie)
                    
                logging.info("Cookieを正常に読み込み、ログイン状態を復元しました。")
                # ログイン確認のため、再度ページを読み込み
                _driver.get("https://x.com/home")

                # ページが完全に読み込まれ、操作可能になるまで待機する
                try:
                    wait = WebDriverWait(_driver, 15)
                    # タイムラインの主要なコンテナが表示されるのを待つ
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="primaryColumn"]')))
                    logging.info("Xのホームページが正常に読み込まれました。")
                except Exception as e:
                    logging.error(f"Xのホームページの読み込み待機中にタイムアウトまたはエラーが発生しました: {e}")
                    close_driver()
                    raise e

            except Exception as e:
                logging.error(f"Cookieの読み込み中にエラーが発生しました: {e}")
                close_driver()
                raise e

        except Exception as e:
            logging.error(f"WebDriverのセットアップ中にエラーが発生しました: {e}")
            raise e
            
    return _driver

def close_driver():
    """
    グローバルなWebDriverインスタンスを終了します。
    """
    global _driver
    if _driver:
        _driver.quit()
        _driver = None
        logging.info("WebDriverインスタンスを終了しました。")

def setup_driver(headless: bool = True, max_retries: int = 3) -> webdriver.Chrome | None:
    """
    Selenium WebDriverをセットアップし、Cookieを使ってログイン状態を復元します。
    ホームページの読み込みに失敗した場合、指定された回数だけ再試行します。
    """
    options = Options()
    if headless:
        options.add_argument("--headless")
        logging.info("ヘッドレスモードでWebDriverを起動します。")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument('--log-level=3') # INFO, WARNING, ERROR 以外のログを抑制

    # WebDriverのセットアップ
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        logging.info("新しいWebDriverインスタンスを初期化しました。")
    except Exception as e:
        logging.error(f"WebDriverの初期化中にエラーが発生しました: {e}")
        return None

    # Cookieの読み込みとホームページへのアクセス（リトライ処理付き）
    for attempt in range(max_retries):
        try:
            logging.info(f"ホームページへのアクセスを試みます... ({attempt + 1}/{max_retries})")
            driver.get(LOGIN_URL) # まずログインページにアクセス

            # Cookieの読み込み
            if os.path.exists(COOKIE_FILE):
                with open(COOKIE_FILE, "rb") as f:
                    cookies = pickle.load(f)
                for cookie in cookies:
                    # 'sameSite'が'None'の場合、'secure'属性が必要になることがある
                    if 'sameSite' in cookie and cookie['sameSite'] == 'None':
                        cookie['secure'] = True
                    driver.add_cookie(cookie)
                logging.info("Cookieを正常に読み込み、ログイン状態を復元しました。")
            else:
                logging.warning("Cookieファイルが見つかりません。ログインページから手動でログインしてください。")

            # ホームページに再度アクセスしてログイン状態を確認
            driver.get("https://x.com/home")

            # ページの主要な要素が表示されるまで待機
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            logging.info("Xのホームページが正常に読み込まれました。")
            return driver # 成功したらdriverインスタンスを返す

        except TimeoutException as e:
            logging.warning(f"ホームページの読み込み中にタイムアウトしました。({attempt + 1}/{max_retries})")
            if attempt == max_retries - 1:
                logging.error(f"最大リトライ回数({max_retries}回)に達しました。ホームページの読み込みに失敗しました。")
                driver.quit()
                return None
            logging.info("リトライします...")
            time.sleep(5) # 5秒待ってからリトライ
        except WebDriverException as e:
            logging.error(f"WebDriver関連のエラーが発生しました: {e} ({attempt + 1}/{max_retries})")
            if attempt == max_retries - 1:
                logging.error(f"最大リトライ回数({max_retries}回)に達しました。WebDriverエラーにより処理を中断します。")
                driver.quit()
                return None
            logging.info("リトライします...")
            time.sleep(5)
        except Exception as e:
            logging.error(f"Cookieの読み込みまたはページ遷移中に予期せぬエラーが発生しました: {e}", exc_info=True)
            driver.quit()
            return None
    
    return None # ループが正常に終了した場合（通常は起こらない）

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