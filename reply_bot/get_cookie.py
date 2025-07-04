import os
import pickle
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

COOKIE_PATH = "./cookie/twitter_cookies_01.pkl"

def save_cookie_after_login():
    # Chromeをウィンドウ付きで起動（自動で閉じない）
    options = Options()
    options.add_experimental_option("detach", True)
    driver = webdriver.Chrome(options=options)

    driver.get("https://twitter.com/login")
    print("ログインを手動で行ってください。完了したらEnterキーを押してください。")

    input()  # 手動ログイン完了後にEnterを押す

    # Cookieを保存
    cookies = driver.get_cookies()
    os.makedirs(os.path.dirname(COOKIE_PATH), exist_ok=True)
    with open(COOKIE_PATH, "wb") as f:
        pickle.dump(cookies, f)

    print(f"✅ Cookieを保存しました：{COOKIE_PATH}")
    driver.quit()

if __name__ == "__main__":
    save_cookie_after_login()
