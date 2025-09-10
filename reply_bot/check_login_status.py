import logging
import time
import argparse
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 通常のインポート - モジュールとして実行される場合
try:
    from .utils import setup_driver
except ImportError:
    # 直接実行される場合のフォールバック
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from reply_bot.utils import setup_driver

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Chrome Profile Managerのログレベルも設定
logging.getLogger('shared_modules.chrome_profile_manager').setLevel(logging.INFO)

def check_login(headless: bool = False):
    """
    setup_driverを使用してブラウザを起動し、Twitterへのログイン状態を確認する。
    
    Args:
        headless: ヘッドレスモードで実行するか
    """
    logging.info("ログイン状態の確認を開始します...")
    driver = None
    try:
        # headlessパラメータを引数として受け取る
        driver = setup_driver(headless=headless)
        if not driver:
            logging.error("WebDriverのセットアップに失敗しました。")
            return

        logging.info("Twitterのホーム画面にアクセスします: https://x.com/home")
        driver.get("https://x.com/home")
        
        # ログインしている場合に表示されるはずの要素を特定
        # 例：サイドナビゲーションにある「投稿する」ボタン
        login_indicator_selector = '[data-testid="SideNav_NewTweet_Button"]'
        
        # ログインのために長時間待機（5分）
        wait = WebDriverWait(driver, 300) # 待機時間を300秒（5分）に設定

        logging.info(f"ログイン確認用の要素 ({login_indicator_selector}) が表示されるか待機します...")
        logging.info("⏰ 手動でログインしてください。最大5分間お待ちします...")

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, login_indicator_selector)))
            logging.info(">>> ログイン成功: 確認用要素が見つかりました。")
            
            # スクリーンショットを保存して証拠を残す
            screenshot_path = "login_success_check.png"
            driver.save_screenshot(screenshot_path)
            logging.info(f"現在の画面のスクリーンショットを {screenshot_path} に保存しました。")

        except Exception:
            logging.error(">>> ログイン失敗: 5分以内にログインが完了しませんでした。")
            logging.warning("ログインページにリダイレクトされているか、UIが変更された可能性があります。")
            logging.info("💡 ヒント: ブラウザが表示されている間に手動でログインしてください。")
            
            # 失敗した時点でのスクリーンショットを保存
            screenshot_path = "login_failure_check.png"
            driver.save_screenshot(screenshot_path)
            logging.info(f"現在の画面のスクリーンショットを {screenshot_path} に保存しました。")

        # ログイン完了後の確認のために10秒間待機
        logging.info("10秒後にブラウザを閉じます...")
        time.sleep(10)

    except Exception as e:
        logging.error(f"ログイン確認処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            logging.info("WebDriverを終了しました。")

def main():
    """エントリーポイント"""
    parser = argparse.ArgumentParser(description="Twitterのログイン状態を確認します。")
    parser.add_argument('--headless', action='store_true', help='このフラグを立てると、ブラウザをヘッドレスモード（非表示）で起動します。')
    parser.add_argument('--debug', action='store_true', help='デバッグログを有効にします。')
    args = parser.parse_args()
    
    # デバッグモードの設定
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger('shared_modules.chrome_profile_manager').setLevel(logging.DEBUG)
        logging.info("デバッグモードが有効になりました。")
    
    check_login(headless=args.headless)

if __name__ == '__main__':
    main()