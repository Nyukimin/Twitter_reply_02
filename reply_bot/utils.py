import logging
import pickle
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from .config import LOGIN_URL, LOGIN_TIMEOUT_ENABLED, LOGIN_TIMEOUT_SECONDS, PAGE_LOAD_TIMEOUT_SECONDS

COOKIE_PATH = "cookie/twitter_cookies_01.pkl"

def setup_driver(headless=True):
    """
    Selenium WebDriverをセットアップし、Cookieを読み込んでログイン状態にします。
    
    Args:
        headless (bool): ヘッドレスモードでブラウザを起動するかどうか。
    
    Returns:
        webdriver.Chrome: セットアップ済みのWebDriverインスタンス。
    """
    logging.info("====== WebDriver manager ======")
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument('--disable-gpu')
    options.add_argument("--window-size=1920x1080")
    
    # WebDriverの自動管理
    service = ChromeService(ChromeDriverManager().install())
    
    driver = webdriver.Chrome(service=service, options=options)
    logging.info("Selenium WebDriverを起動しました。")

    if LOGIN_TIMEOUT_ENABLED:
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
        
    try:
        logging.info("Cookieを読み込み、ブラウザにセットします")
        driver.get(LOGIN_URL)
        
        with open(COOKIE_PATH, "rb") as f:
            cookies = pickle.load(f)
        for cookie in cookies:
            driver.add_cookie(cookie)
        
        # Cookieをセットした後、再度ページを読み込む
        driver.get(LOGIN_URL)
        logging.info("Cookieをブラウザにセットしました。")

    except FileNotFoundError:
        logging.error(f"Cookieファイルが見つかりません: {COOKIE_PATH}")
        logging.error("先に 'get_cookie.py' を実行して、Cookieファイルを作成してください。")
        driver.quit()
        return None
    except Exception as e:
        logging.error(f"Cookieの読み込みまたはセット中にエラーが発生しました: {e}")
        driver.quit()
        return None
        
    return driver 