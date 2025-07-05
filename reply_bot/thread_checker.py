import logging
from typing import List, Dict, Tuple
import csv
import os
import re
import time
import pickle
import pandas as pd
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException

from .config import TARGET_USER, PRIORITY_REPLY_ENABLED, MAX_MY_THREAD_REPLIES, MAX_OTHER_THREAD_REPLIES
from .utils import setup_driver

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# グローバル変数として WebDriver インスタンスを保持
driver = None

def get_thread_origin_author(tweet_url: str, driver) -> str:
    """
    指定されたツイートURLからスレッドの起点となるツイートの投稿者を取得します。
    """
    try:
        logging.info(f"ツイートページにアクセス中: {tweet_url}")
        driver.get(tweet_url)
        time.sleep(3) # ユーザーの指示通り3秒待機
        
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
        )
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # ページ内の最初の<article>要素が起点ツイートだと仮定
        tweet_articles = soup.find_all('article', {'data-testid': 'tweet'})
        if not tweet_articles:
            logging.warning("ツイート要素が見つかりませんでした。")
            return None
            
        root_tweet = tweet_articles[0]
        
        user_name_div = root_tweet.find('div', {'data-testid': 'User-Name'})
        if user_name_div:
            # ユーザーIDは screen_name として a タグの href に含まれる
            user_link = user_name_div.find('a', {'role': 'link', 'href': lambda href: href and href.startswith('/') and '/status/' not in href})
            if user_link and 'href' in user_link.attrs:
                author_id = user_link['href'].lstrip('/')
                logging.info(f"スレッドの起点投稿者を特定しました: {author_id}")
                return author_id

        logging.warning("スレッドの起点投稿者が見つかりませんでした。")
        return None

    except TimeoutException:
        logging.error(f"ページのロード中にタイムアウトしました: {tweet_url}")
        return None
    except Exception as e:
        logging.error(f"起点投稿者の取得中にエラーが発生しました: {e}", exc_info=True)
        return None

def check_and_update_thread_origin(replies_data: List[Dict], driver) -> List[Dict]:
    """
    各リプライのスレッド起点が自分自身かを確認し、'is_my_thread' を更新します。
    """
    updated_replies = []
    
    for reply in replies_data:
        # UserID と reply_id からツイートのURLを構築
        tweet_url = f"https://x.com/{reply['UserID']}/status/{reply['reply_id']}"
        root_author = get_thread_origin_author(tweet_url, driver)
        
        # is_my_thread フラグを上書き
        if root_author and root_author == TARGET_USER:
            reply['is_my_thread'] = True
            logging.info(f"自分のスレッドのリプライ（再判定）: {reply.get('reply_id')}")
        else:
            reply['is_my_thread'] = False
            logging.info(f"他人のスレッドのリプライ（再判定）: {reply.get('reply_id')} (起点: {root_author})")
        
        updated_replies.append(reply)
            
    return updated_replies

def get_priority_replies(replies_data: List[Dict], driver) -> List[Dict]:
    """
    優先度に基づいてリプライを選択します。
    PRIORITY_REPLY_ENABLED が False の場合は、全件をそのまま返します。
    """
    if not PRIORITY_REPLY_ENABLED:
        logging.info("優先度判定はOFFです。取得したすべてのリプライを処理対象とします。")
        return replies_data

    logging.info("優先度判定がONです。リプライをフィルタリングします。")
    # 注意: この関数は is_my_thread が事前に設定されていることを前提とします。
    my_thread_replies = [r for r in replies_data if r.get('is_my_thread')]
    other_thread_replies = [r for r in replies_data if not r.get('is_my_thread')]
    
    selected_my_thread = my_thread_replies[:MAX_MY_THREAD_REPLIES]
    selected_other_thread = other_thread_replies[:MAX_OTHER_THREAD_REPLIES]
    
    priority_replies = selected_my_thread + selected_other_thread
    
    logging.info(f"優先度順に選択されたリプライ数: {len(priority_replies)}")
    logging.info(f"  - 自分のスレッド: {len(selected_my_thread)} (最大: {MAX_MY_THREAD_REPLIES})")
    logging.info(f"  - 他人のスレッド: {len(selected_other_thread)} (最大: {MAX_OTHER_THREAD_REPLIES})")
    
    return priority_replies

# --- 以下、単体実行用のロジック ---

def load_replies_from_csv(csv_path: str):
    """CSVファイルからリプライデータを読み込み、リストに変換します"""
    replies = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['is_my_thread'] = row.get('is_my_thread', 'false').lower() == 'true'
            row['reply_num'] = int(row.get('reply_num', 0) or 0)
            row['like_num'] = int(row.get('like_num', 0) or 0)
            replies.append(row)
    return replies

def write_replies_to_csv(replies: list, output_path: str):
    """リプライデータをCSVファイルに書き込みます"""
    if not replies:
        logging.warning("書き込むリプライデータがありません。")
        return
        
    fieldnames = replies[0].keys()
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(replies)
    logging.info(f"結果を {output_path} に保存しました。")

def main_process(input_csv: str) -> str | None:
    """
    入力CSVを読み込み、スレッドの起点を確認・更新し、結果を新しいCSVに出力します。
    """
    logging.info(f"'{input_csv}' からデータを読み込みます...")
    try:
        df = pd.read_csv(input_csv)
        replies_data = df.to_dict('records')
        logging.info(f"CSVから {len(replies_data)} 件のリプライを読み込みました。")
    except FileNotFoundError:
        logging.error(f"入力ファイルが見つかりません: {input_csv}")
        return None
    except Exception as e:
        logging.error(f"CSVファイルの読み込み中にエラーが発生しました: {e}")
        return None

    # 出力ファイルパスの決定
    base_name = os.path.basename(input_csv)
    name_part = base_name.replace('extracted_tweets_', '')
    output_csv = os.path.join(os.path.dirname(input_csv), f"priority_replies_rechecked_{name_part}")

    driver = None
    try:
        driver = setup_driver(headless=False)
        if not driver:
            return None
            
        logging.info("--- スレッド起点の確認と更新を行います ---")
        checked_replies = check_and_update_thread_origin(replies_data, driver)
    
        # 優先度付けが有効な場合のみフィルタリング
        if PRIORITY_REPLY_ENABLED:
            logging.info("--- 優先度に基づいてリプライをフィルタリングします ---")
            final_replies = get_priority_replies(checked_replies, driver)
        else:
            logging.info("--- 優先度フィルタリングは無効です。全ての結果を出力します ---")
            final_replies = checked_replies
            
        logging.info(f"--- 結果をCSVに出力します ({len(final_replies)} 件) ---")
        write_replies_to_csv(final_replies, output_csv)
        return output_csv

    except Exception as e:
        logging.error(f"処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        return None
    finally:
        if driver:
            driver.quit()
            logging.info("Selenium WebDriverを終了しました。")

def main_test(input_csv: str):
    """
    単体テスト用のメイン関数。先頭5件のみを処理し、フィルタリングせずに全件出力する。
    """
    logging.info(f"'{input_csv}' からテストデータを読み込みます...")
    try:
        df = pd.read_csv(input_csv)
        replies_data = df.to_dict('records')
        logging.info(f"CSVから {len(replies_data)} 件のリプライを読み込みました。")
    except FileNotFoundError:
        logging.error(f"入力ファイルが見つかりません: {input_csv}")
        return
    
    # 出力ファイルパスの決定
    base_name = os.path.basename(input_csv)
    name_part = base_name.replace('extracted_tweets_', '')
    output_csv = os.path.join(os.path.dirname(input_csv), f"priority_replies_rechecked_{name_part}")

    driver = None
    try:
        driver = setup_driver(headless=False) # テスト時はブラウザ表示
        if not driver:
            return
        
        logging.info("--- スレッド起点の確認と更新を行います ---")
        # 最初の5件に絞ってテスト
        checked_replies = check_and_update_thread_origin(replies_data[:5], driver)
    
        logging.info("--- テスト結果をCSVに出力します ---")
        write_replies_to_csv(checked_replies, output_csv)
    
    except Exception as e:
        logging.error(f"テスト実行中にエラーが発生しました: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            logging.info("Selenium WebDriverを終了しました。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='リプライのスレッド起点を確認し、CSVを更新します。')
    parser.add_argument('input_csv', type=str, help='入力CSVファイルのパス')
    parser.add_argument('--test', action='store_true', help='このフラグを立てると、先頭5件のみを処理するテストモードで実行します。')

    args = parser.parse_args()

    if args.test:
        main_test(args.input_csv)
    else:
        main_process(args.input_csv) 