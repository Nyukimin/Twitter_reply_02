import pickle
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import os

from .config import LOGIN_URL, USERNAME, PASSWORD

COOKIE_FILE = "cookie/twitter_cookies_01.pkl"

def get_cookies_and_login():
    options = Options()
    # ヘッドレスモードを無効にしてブラウザ表示を許可
    # options.add_argument('--headless')

    # WebDriverのセットアップ
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        # ログインページへアクセス
        driver.get(LOGIN_URL)
        print("Xのログインページを開きました。手動でログインしてください。\nログインが完了したら、このコンソールに戻り、任意のキーを押してください。")
        
        # ユーザーにログインを促すための待機
        input("ログイン後、Enterキーを押してください...\n")

        # ログイン後のCookieを取得
        cookies = driver.get_cookies()
        
        # Cookieディレクトリが存在しない場合は作成
        os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)

        # Cookieをファイルに保存
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(cookies, f)
        print(f"Cookieを {COOKIE_FILE} に保存しました。")

    except Exception as e:
        print(f"Cookie取得中にエラーが発生しました: {e}")
    finally:
        driver.quit()


def load_cookies_and_navigate(driver: webdriver.Chrome):
    if not os.path.exists(COOKIE_FILE):
        print(f"Cookieファイル {COOKIE_FILE} が見つかりません。最初に get_cookies_and_login() を実行してください。")
        return False

    with open(COOKIE_FILE, "rb") as f:
        cookies = pickle.load(f)

    driver.get("https://x.com/") # ドメインにアクセスしてCookieをセット可能にする
    for cookie in cookies:
        # Seleniumが期待する形式に調整 (expiresがfloatの場合があるため)
        if 'expiry' in cookie: # 'expires'がdeprecatedで'expiry'が新しい
            cookie['expiry'] = int(cookie['expiry'])
        elif 'expires' in cookie: # 古いバージョンとの互換性のため
             cookie['expiry'] = int(cookie['expires'])
        
        driver.add_cookie(cookie)
    
    print("Cookieを読み込み、ブラウザにセットしました。")
    return True

if __name__ == "__main__":
    get_cookies_and_login()
