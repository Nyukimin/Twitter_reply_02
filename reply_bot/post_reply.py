import pandas as pd
import argparse
import logging
import time
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .utils import setup_driver

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def like_tweet(driver, tweet_id: str, dry_run: bool = True):
    """
    指定されたツイートIDのページに移動し、「いいね」します。
    """
    # 実際にはuser_idも必要だが、URL直接指定なら不要
    tweet_url = f"https://x.com/any/status/{tweet_id}"
    logging.info(f"ツイートページにアクセス中: {tweet_url}")
    driver.get(tweet_url)
    
    try:
        # "いいね"ボタンが表示されるまで待機
        like_button_selector = '[data-testid="like"]'
        wait = WebDriverWait(driver, 15)
        like_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, like_button_selector)))
        
        if dry_run:
            logging.info(f"[DRY RUN] tweet_id: {tweet_id} に「いいね」をします。")
        else:
            logging.info(f"tweet_id: {tweet_id} に「いいね」をします。")
            like_button.click()
            time.sleep(1) # アクション後の待機

    except Exception as e:
        logging.error(f"tweet_id: {tweet_id} の「いいね」中にエラーが発生しました: {e}")

def post_reply_to_tweet(driver, tweet_id: str, reply_text: str, dry_run: bool = True):
    """
    指定されたツイートIDのページに移動し、返信を投稿します。
    """
    tweet_url = f"https://x.com/any/status/{tweet_id}"
    logging.info(f"返信対象のツイートページにアクセス中: {tweet_url}")
    driver.get(tweet_url)

    try:
        # 返信入力欄が表示されるまで待機
        reply_input_selector = '[data-testid="tweetTextarea_0"]'
        wait = WebDriverWait(driver, 15)
        reply_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, reply_input_selector)))
        
        if dry_run:
            logging.info(f"[DRY RUN] tweet_id: {tweet_id} に以下の内容で返信します:\n--- MOCK REPLY ---\n{reply_text}\n--------------------")
        else:
            logging.info(f"tweet_id: {tweet_id} に返信します...")
            reply_input.send_keys(reply_text)
            
            # 返信ボタンをクリック
            reply_button_selector = '[data-testid="tweetButton"]'
            reply_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, reply_button_selector)))
            reply_button.click()
            logging.info("返信を投稿しました。")
            time.sleep(3) # アクション後の待機
            
    except Exception as e:
        logging.error(f"tweet_id: {tweet_id} への返信中にエラーが発生しました: {e}")


def main_process(input_csv: str, dry_run: bool = True):
    """
    CSVを読み込み、各リプライに対して「いいね」と「返信」を行います。
    """
    if dry_run:
        logging.info("=== ドライランモードで実行します ===")
    else:
        logging.warning("★★★ ライブモードで実行します ★★★")
        
    try:
        df = pd.read_csv(input_csv)
    except FileNotFoundError:
        logging.error(f"入力ファイルが見つかりません: {input_csv}")
        return

    # generated_replyが空でない行に絞り込む
    replies_to_post = df.dropna(subset=['generated_reply']).copy()
    
    if replies_to_post.empty:
        logging.info("投稿対象の返信が見つかりませんでした。")
        return
        
    driver = setup_driver(headless=False) # 操作を確認するためヘッドフルで起動
    if not driver:
        return

    try:
        for index, row in replies_to_post.iterrows():
            tweet_id = row['reply_id']
            generated_reply = row['generated_reply']
            
            logging.info(f"--- 処理中: {index + 1}/{len(replies_to_post)} (tweet_id: {tweet_id}) ---")
            
            # 1. いいねを押す
            like_tweet(driver, tweet_id, dry_run)
            
            # 2. 返信する
            post_reply_to_tweet(driver, tweet_id, generated_reply, dry_run)
            
            time.sleep(5) # 次の処理までのクールダウン

    finally:
        logging.info("全ての処理が完了しました。WebDriverを終了します。")
        driver.quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成された返信をXに投稿します。')
    parser.add_argument('input_csv', type=str, help='入力CSVファイルのパス (例: output/generated_replies_....csv)')
    parser.add_argument('--live-run', action='store_true', help='このフラグを立てると、実際に投稿やいいねを行います（ドライランを無効化）。')
    
    args = parser.parse_args()
    
    # --live-run フラグがなければ dry_run は True
    is_dry_run = not args.live_run
    
    main_process(args.input_csv, dry_run=is_dry_run) 