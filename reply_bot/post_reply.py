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
from selenium import webdriver

from .utils import setup_driver
from .config import POST_INTERVAL_SECONDS, TARGET_USER

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main_process(driver: webdriver.Chrome, input_csv: str, dry_run: bool = True, limit: int | None = None, interval: int = 15):
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
        
    if not driver:
        logging.error("有効なWebDriverインスタンスが渡されませんでした。")
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
            wait = WebDriverWait(driver, 20) # 待機時間を20秒に延長

            # ★ 新規追加: ツイート本文が表示されるまで待機することで、ページの読み込みを確実にする
            try:
                logging.info("ツイート本文が表示されるまで待機します...")
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetText"]')))
                logging.info("ツイート本文の表示を確認しました。")
            except Exception as e:
                logging.warning(f"ツイート本文の読み込み中にタイムアウトしました。処理を続行しますが、失敗する可能性があります。: {e}")

            # 2. 「いいね」処理
            if like_num == 0:
                try:
                    # ユーザーの指示により、data-testid="like"方式に戻す
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
                    # ★★★ 重複返信チェックを追加 ★★★
                    logging.info("既存の返信をスキャンして、重複投稿でないか確認します...")
                    # 自分のユーザーIDを含むリンクを探す
                    my_reply_xpath = f"//a[contains(@href, '/{TARGET_USER}') and .//span[contains(text(), '@{TARGET_USER}')]]"
                    
                    try:
                        # 0.5秒の短い待機で存在チェック（要素があればすぐ見つかるはず）
                        short_wait = WebDriverWait(driver, 0.5)
                        short_wait.until(EC.presence_of_element_located((By.XPATH, my_reply_xpath)))
                        logging.warning(f"★★★ 既に @{TARGET_USER} からの返信が見つかりました。このツイートへの投稿はスキップします。")
                        # forループの次のイテレーションに移動
                        continue
                    except Exception:
                        # 見つからなかった場合は正常
                        logging.info("重複投稿は検出されませんでした。返信処理を続行します。")

                    reply_input_selector = '[data-testid="tweetTextarea_0"]'
                    reply_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, reply_input_selector)))
                    
                    if dry_run:
                        logging.info(f"[DRY RUN] tweet_id: {tweet_id} に以下の内容で返信します:\n--- MOCK REPLY ---\n{generated_reply}\n--------------------")
                    else:
                        logging.info(f"tweet_id: {tweet_id} に返信します...")
                        
                        # クリップボード経由の操作
                        logging.info("返信ボックスにフォーカスを試みます。")
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, reply_input_selector)))
                        driver.execute_script("arguments[0].focus(); arguments[0].click();", reply_input)
                        time.sleep(1) # フォーカス後の待機

                        logging.info("返信内容をクリップボード経由で貼り付けます。")
                        
                        final_reply_text = generated_reply.replace('<br>', '\n')
                        pyperclip.copy(final_reply_text)
                        
                        reply_input.send_keys(Keys.CONTROL, 'v')
                        time.sleep(0.5)

                        logging.info("Ctrl+Enterで返信を投稿します...")
                        reply_input.send_keys(Keys.CONTROL, Keys.ENTER)
                        
                        logging.info("返信を投稿しました。")
                        # 投稿後の待機はいいねの後に入れるため、ここでは短くする
                        time.sleep(2) 

                except Exception as e:
                    logging.error(f"tweet_id: {tweet_id} への返信中にエラーが発生しました: {e}")
            else:
                logging.info(f"tweet_id: {tweet_id} は自分のスレッドではないため、返信をスキップします。")

            logging.info(f"次の処理までのクールダウン ({interval}秒)")
            time.sleep(interval)
    except Exception as e:
        logging.error(f"投稿処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
    logging.info("投稿処理のサイクルが完了しました。")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成された返信をXに投稿します。')
    parser.add_argument('input_csv', type=str, help='入力CSVファイルのパス (例: output/generated_replies_....csv)')
    parser.add_argument('--live-run', action='store_true', help='このフラグを立てると、実際に投稿やいいねを行います（ドライランを無効化）。')
    parser.add_argument('--limit', type=int, default=None, help='処理するツイートの最大数を指定します。')
    parser.add_argument('--interval', type=int, default=None, help=f'投稿間の待機時間（秒）。指定しない場合はconfig.pyの値({POST_INTERVAL_SECONDS}秒)が使われます。')
    
    args = parser.parse_args()
    
    # --live-run フラグがなければ dry_run は True
    is_dry_run = not args.live_run

    # インターバル時間が引数で指定されていればそれを使い、なければconfigから取得
    interval_to_use = args.interval if args.interval is not None else POST_INTERVAL_SECONDS
    
    # 単体実行時のみ、driverの起動と終了をここで行う
    driver = None
    try:
        # ユーザーの記憶に基づき、デバッグ中はFalseを維持 [[memory:2213753]]
        driver = setup_driver(headless=False)
        if driver:
            main_process(driver, args.input_csv, dry_run=is_dry_run, limit=args.limit, interval=interval_to_use)
    finally:
        if driver:
            driver.quit()
            logging.info("Selenium WebDriverを終了しました。") 