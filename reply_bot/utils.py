import logging
import pickle
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from .config import LOGIN_URL, LOGIN_TIMEOUT_ENABLED, LOGIN_TIMEOUT_SECONDS, PAGE_LOAD_TIMEOUT_SECONDS

COOKIE_FILE = "cookie/twitter_cookies_01.pkl"

def setup_driver(headless: bool = True) -> webdriver.Chrome | None:
    """
    Selenium WebDriverをセットアップし、Cookieを読み込んでログイン状態にします。
    ヘッドレスモードは引数で制御できます。
    """
    options = Options()
    if headless:
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        logging.info("WebDriverをセットアップしました。")
    except Exception as e:
        logging.error(f"WebDriverのセットアップ中にエラーが発生しました: {e}")
        return None

    # Cookieを読み込んでログイン
    if not os.path.exists(COOKIE_FILE):
        logging.error(f"Cookieファイル {COOKIE_FILE} が見つかりません。")
        logging.error("最初に 'python -m reply_bot.get_cookie' を実行して、ログインとCookieの保存を完了させてください。")
        driver.quit()
        return None

    try:
        with open(COOKIE_FILE, "rb") as f:
            cookies = pickle.load(f)
        
        # Cookieをセットするために、一度ドメインにアクセス
        # LOGIN_URLはドメインが同じなのでCookieセットに利用可能
        driver.get("https://x.com/") 
        
        for cookie in cookies:
            if 'expiry' in cookie:
                cookie['expiry'] = int(cookie['expiry'])
            driver.add_cookie(cookie)
            
        logging.info("Cookieを正常に読み込み、ログイン状態を復元しました。")
        # ログイン確認のため、再度ページを読み込み
        driver.get("https://x.com/home")

        return driver

    except Exception as e:
        logging.error(f"Cookieの読み込み中にエラーが発生しました: {e}")
        driver.quit()
        return None

    if LOGIN_TIMEOUT_ENABLED:
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
        
    try:
        logging.info("Cookieを読み込み、ブラウザにセットします")
        driver.get(LOGIN_URL)
        
        with open(COOKIE_FILE, "rb") as f:
            cookies = pickle.load(f)
        for cookie in cookies:
            driver.add_cookie(cookie)
        
        # Cookieをセットした後、再度ページを読み込む
        driver.get(LOGIN_URL)
        logging.info("Cookieをブラウザにセットしました。")

    except FileNotFoundError:
        logging.error(f"Cookieファイルが見つかりません: {COOKIE_FILE}")
        logging.error("先に 'get_cookie.py' を実行して、Cookieファイルを作成してください。")
        driver.quit()
        return None
    except Exception as e:
        logging.error(f"Cookieの読み込みまたはセット中にエラーが発生しました: {e}")
        driver.quit()
        return None
        
    return driver 