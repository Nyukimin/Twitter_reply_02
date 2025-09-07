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

from .utils import setup_driver, check_memory_usage, force_restart_driver
from .config import POST_INTERVAL_SECONDS, TARGET_USER
from .webdriver_stabilizer import WebDriverStabilizer, safe_execute, handle_webdriver_error

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main_process(driver: webdriver.Chrome, input_csv: str, dry_run: bool = True, limit: int | None = None, interval: int = 15):
    """
    CSVを読み込み、各リプライに対してページアクセスを1回に最適化し、
    「いいね」と「返信」を行います。
    処理の進捗（いいね）はCSVファイルに追記され、再実行時に完了したタスクをスキップします。
    返信すべきかどうかは、実行時のスレッドの状態を見て動的に判断します。
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

    # 'liked' 列が存在しない場合はFalseで初期化（'posted'列は動的に判断するため不要）
    if 'liked' not in df.columns:
        df['liked'] = False
    df['liked'] = df['liked'].fillna(False).astype(bool)

    # 全ツイートを処理対象とする（いいね処理のため）
    replies_to_process = df.copy()
    
    if limit is not None and limit > 0:
        logging.info(f"処理件数を {limit} 件に制限します。")
        replies_to_process = replies_to_process.head(limit)
        
    if replies_to_process.empty:
        logging.info("処理対象のツイートが見つかりませんでした。")
        return
        
    if not driver:
        logging.error("有効なWebDriverインスタンスが渡されませんでした。")
        return

    something_changed = False
    try:
        for index, row in replies_to_process.iterrows():
            tweet_id = row['reply_id']
            generated_reply = row['generated_reply']
            is_my_thread = row.get('is_my_thread', False)
            is_liked = row['liked']
            
            logging.info(f"--- 処理中: {df.index.get_loc(index) + 1}/{len(df)} (tweet_id: {tweet_id}) ---")
            
            # 1. ページにアクセス
            tweet_url = f"https://x.com/any/status/{tweet_id}"
            logging.info(f"ツイートページにアクセス中: {tweet_url}")
            driver.get(tweet_url)
            wait = WebDriverWait(driver, 20)

            try:
                logging.info("ツイート本文が表示されるまで待機します...")
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweetText"]')))
                logging.info("ツイート本文の表示を確認しました。")
            except Exception as e:
                logging.warning(f"ツイート本文の読み込み中にタイムアウトしました。処理を続行しますが、失敗する可能性があります。: {e}")

            # 2. 「いいね」処理 (未実施の場合)
            if not is_liked:
                try:
                    like_button_selector = '[data-testid="like"]'
                    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, like_button_selector)))
                    if dry_run:
                        logging.info(f"[DRY RUN] tweet_id: {tweet_id} に「いいね」をします。")
                    else:
                        logging.info(f"tweet_id: {tweet_id} に「いいね」をします。")
                        like_button = driver.find_element(By.CSS_SELECTOR, like_button_selector)
                        driver.execute_script("arguments[0].click();", like_button)
                        df.loc[index, 'liked'] = True
                        something_changed = True
                        time.sleep(1)
                except Exception as e:
                    # 「いいね」しようとして、すでにされているなどの理由でボタンが見つからないケースは警告に留める
                    logging.warning(f"tweet_id: {tweet_id} の「いいね」中に問題が発生しました（すでに「いいね」済みの可能性があります）: {e}")
            else:
                logging.info(f"tweet_id: {tweet_id} はCSV上で「いいね」済みのためスキップします。")

            # 3. 返信処理 (generated_replyが存在する場合のみ実行)
            if generated_reply and str(generated_reply).strip():
                should_reply = True
                logging.info("返信コメントが存在します。返信の重複チェック（後続ツイートの有無）を行います...")
                try:
                    # ページ上に存在するすべてのツイート要素を取得
                    all_tweet_elements = driver.find_elements(By.XPATH, '//article[@data-testid="tweet"]')
                    
                    target_tweet_index = -1
                    # まず、URLに含まれるIDと一致する「返信対象のツイート」が何番目にあるかを探す
                    for i, tweet_element in enumerate(all_tweet_elements):
                        try:
                            # ツイート内のタイムスタンプなどのリンクにIDが含まれているかチェック
                            tweet_element.find_element(By.XPATH, f".//a[contains(@href, '/status/{tweet_id}')]")
                            target_tweet_index = i
                            logging.info(f"返信対象のツイートを {i + 1}番目に発見しました。")
                            break
                        except Exception:
                            continue
                    
                    if target_tweet_index == -1:
                        logging.error("ページ内で返信対象のツイートが見つかりませんでした。安全のため返信をスキップします。")
                        should_reply = False
                    else:
                        # 返信対象のツイートより後にツイート（＝後続の返信）があるか
                        if len(all_tweet_elements) > target_tweet_index + 1:
                            num_replies = len(all_tweet_elements) - (target_tweet_index + 1)
                            logging.warning(f"対象ツイートの後に {num_replies} 件の返信が見つかりました。返信をスキップします。")
                            should_reply = False
                        else:
                            logging.info("対象ツイートの後に返信はありません。返信可能です。")

                except Exception as e:
                    logging.error(f"返信の重複チェック中に予期せぬエラーが発生しました: {e}", exc_info=True)
                    should_reply = False # 安全のため、チェックに失敗した場合は投稿しない

                if should_reply:
                    try:
                        logging.info("返信処理を開始します。")
                        reply_input_selector = '[data-testid="tweetTextarea_0"]'
                        reply_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, reply_input_selector)))
                        
                        if dry_run:
                            logging.info(f"[DRY RUN] tweet_id: {tweet_id} に以下の内容で返信します:\n--- MOCK REPLY ---\n{generated_reply}\n--------------------")
                        else:
                            logging.info(f"tweet_id: {tweet_id} に返信します...")
                            
                            driver.execute_script("arguments[0].focus(); arguments[0].click();", reply_input)
                            time.sleep(1)

                            final_reply_text = generated_reply.replace('<br>', '\n')
                            pyperclip.copy(final_reply_text)
                            
                            reply_input.send_keys(Keys.CONTROL, 'v')
                            time.sleep(0.5)

                            reply_input.send_keys(Keys.CONTROL, Keys.ENTER)
                            logging.info("返信を投稿しました。")
                            time.sleep(2)
                    except Exception as e:
                        logging.error(f"tweet_id: {tweet_id} への返信中にエラーが発生しました: {e}")
                else:
                    logging.info("重複チェックにより返信がスキップされたため、クールダウンを省略して次の処理へ進みます。")
                    continue
            else:
                logging.info(f"tweet_id: {tweet_id} には返信コメントが生成されていないため、返信対象外です。")

            logging.info(f"次の処理までのクールダウン ({interval}秒)")
            time.sleep(interval)
    except Exception as e:
        logging.error(f"投稿処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        if something_changed and not dry_run:
            logging.info(f"「いいね」のステータスをCSVファイルに書き込みます: {input_csv}")
            df.to_csv(input_csv, index=False, encoding='utf-8-sig')
        else:
            logging.info("ドライランモードまたは「いいね」の変更がなかったため、CSVは更新されませんでした。")
            
    logging.info("投稿処理のサイクルが完了しました。")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成された返信をXに投稿します。')
    parser.add_argument('input_csv', type=str, help='入力CSVファイルのパス (例: output/generated_replies_....csv)')
    parser.add_argument('--live-run', action='store_true', help='このフラグを立てると、実際に投稿やいいねを行います（ドライランを無効化）。')
    parser.add_argument('--limit', type=int, default=None, help='処理するツイートの最大数を指定します。')
    parser.add_argument('--interval', type=int, default=None, help=f'投稿間の待機時間（秒）。指定しない場合はconfig.pyの値({POST_INTERVAL_SECONDS}秒)が使われます。')
    parser.add_argument('--headless', action='store_true', help='このフラグを立てると、ブラウザをヘッドレスモード（非表示）で起動します。')
    
    args = parser.parse_args()
    
    # --live-run フラグがなければ dry_run は True
    is_dry_run = not args.live_run

    # インターバル時間が引数で指定されていればそれを使い、なければconfigから取得
    interval_to_use = args.interval if args.interval is not None else POST_INTERVAL_SECONDS
    
    # 単体実行時のみ、driverの起動と終了をここで行う
    driver = None
    try:
        driver = setup_driver(headless=args.headless)
        if driver:
            main_process(driver, args.input_csv, dry_run=is_dry_run, limit=args.limit, interval=interval_to_use)
    finally:
        if driver:
            driver.quit()
            logging.info("Selenium WebDriverを終了しました。") 