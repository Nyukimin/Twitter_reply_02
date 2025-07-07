import logging
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# このスクリプトは単体で実行されることを想定しているため、
# 親ディレクトリのパスをシステムパスに追加する
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reply_bot.utils import setup_driver

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def check_login():
    """
    setup_driverを使用してブラウザを起動し、Twitterへのログイン状態を確認する。
    """
    logging.info("ログイン状態の確認を開始します...")
    driver = None
    try:
        # headless=Falseでブラウザの動作を目視確認 [[memory:2213753]]
        driver = setup_driver(headless=False)
        if not driver:
            logging.error("WebDriverのセットアップに失敗しました。")
            return

        logging.info("Twitterのホーム画面にアクセスします: https://x.com/home")
        driver.get("https://x.com/home")
        
        # ログインしている場合に表示されるはずの要素を特定
        # 例：サイドナビゲーションにある「投稿する」ボタン
        login_indicator_selector = '[data-testid="SideNav_NewTweet_Button"]'
        
        wait = WebDriverWait(driver, 15) # 待機時間を15秒に設定

        logging.info(f"ログイン確認用の要素 ({login_indicator_selector}) が表示されるか待機します...")

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, login_indicator_selector)))
            logging.info(">>> ログイン成功: 確認用要素が見つかりました。")
            
            # スクリーンショットを保存して証拠を残す
            screenshot_path = "login_success_check.png"
            driver.save_screenshot(screenshot_path)
            logging.info(f"現在の画面のスクリーンショットを {screenshot_path} に保存しました。")

        except Exception:
            logging.error(">>> ログイン失敗: 確認用要素が見つかりませんでした。")
            logging.warning("ログインページにリダイレクトされているか、UIが変更された可能性があります。")
            
            # 失敗した時点でのスクリーンショットを保存
            screenshot_path = "login_failure_check.png"
            driver.save_screenshot(screenshot_path)
            logging.info(f"現在の画面のスクリーンショットを {screenshot_path} に保存しました。")

        # 状態確認のために5秒間待機
        logging.info("5秒後にブラウザを閉じます...")
        time.sleep(5)

    except Exception as e:
        logging.error(f"ログイン確認処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            logging.info("WebDriverを終了しました。")

if __name__ == '__main__':
    check_login() 