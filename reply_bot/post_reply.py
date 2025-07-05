import pandas as pd
import argparse
import logging
import time
import os
import pyperclip
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .utils import setup_driver

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main_process(input_csv: str, dry_run: bool = True, limit: int | None = None):
    """
    CSVを読み込み、各リプライに対してページアクセスを1回に最適化し、
    「いいね」と「返信」を行います。
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
    
    # limitが指定されている場合は、処理件数を制限する
    if limit is not None and limit > 0:
        logging.info(f"処理件数を {limit} 件に制限します。")
        replies_to_post = replies_to_post.head(limit)
        
    if replies_to_post.empty:
        logging.info("投稿対象の返信が見つかりませんでした。")
        return
        
    driver = setup_driver(headless=False)
    if not driver:
        return

    try:
        for index, row in replies_to_post.iterrows():
            tweet_id = row['reply_id']
            generated_reply = row['generated_reply']
            like_num = row['like_num']
            is_my_thread = row.get('is_my_thread', False)
            
            logging.info(f"--- 処理中: {index + 1}/{len(replies_to_post)} (tweet_id: {tweet_id}) ---")
            
            # 1. ページにアクセス (1ツイートにつき1回のみ)
            tweet_url = f"https://x.com/any/status/{tweet_id}"
            logging.info(f"ツイートページにアクセス中: {tweet_url}")
            driver.get(tweet_url)
            wait = WebDriverWait(driver, 15)

            # 2. 「いいね」処理
            if like_num == 0:
                try:
                    like_button_selector = '[data-testid="like"]'
                    like_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, like_button_selector)))
                    if dry_run:
                        logging.info(f"[DRY RUN] tweet_id: {tweet_id} に「いいね」をします。")
                    else:
                        logging.info(f"tweet_id: {tweet_id} に「いいね」をします。")
                        driver.execute_script("arguments[0].click();", like_button)
                        time.sleep(1)
                except Exception as e:
                    logging.error(f"tweet_id: {tweet_id} の「いいね」中にエラーが発生しました: {e}")
            else:
                logging.info(f"tweet_id: {tweet_id} は既に {like_num} 件の「いいね」があるため、スキップします。")

            # 3. 返信処理
            if is_my_thread:
                try:
                    reply_input_selector = '[data-testid="tweetTextarea_0"]'
                    reply_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, reply_input_selector)))
                    
                    if dry_run:
                        logging.info(f"[DRY RUN] tweet_id: {tweet_id} に以下の内容で返信します:\n--- MOCK REPLY ---\n{generated_reply}\n--------------------")
                    else:
                        logging.info(f"tweet_id: {tweet_id} に返信します...")
                        
                        # 確実なフォーカスとペースト
                        reply_input.click() 
                        time.sleep(0.5)
                        pyperclip.copy(generated_reply)
                        reply_input.send_keys(Keys.CONTROL, 'v')
                        time.sleep(0.5)

                        logging.info("Ctrl+Enterで返信を投稿します...")
                        reply_input.send_keys(Keys.CONTROL, Keys.ENTER)
                        
                        logging.info("返信を投稿しました。処理が完了するまで10秒待機します...")
                        time.sleep(10)
                except Exception as e:
                    logging.error(f"tweet_id: {tweet_id} への返信中にエラーが発生しました: {e}")
            else:
                logging.info(f"tweet_id: {tweet_id} は自分のスレッドではないため、返信をスキップします。")
            
            logging.info("次の処理までのクールダウン (5秒)")
            time.sleep(5)

    finally:
        logging.info("全ての処理が完了しました。WebDriverを終了します。")
        driver.quit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成された返信をXに投稿します。')
    parser.add_argument('input_csv', type=str, help='入力CSVファイルのパス (例: output/generated_replies_....csv)')
    parser.add_argument('--live-run', action='store_true', help='このフラグを立てると、実際に投稿やいいねを行います（ドライランを無効化）。')
    parser.add_argument('--limit', type=int, default=None, help='処理するツイートの最大数を指定します。')
    
    args = parser.parse_args()
    
    # --live-run フラグがなければ dry_run は True
    is_dry_run = not args.live_run
    
    main_process(args.input_csv, dry_run=is_dry_run, limit=args.limit) 