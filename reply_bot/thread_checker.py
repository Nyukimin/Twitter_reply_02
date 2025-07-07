import logging
from typing import List, Dict, Tuple
import csv
import os
import re
import time
import pickle
import pandas as pd
from datetime import datetime
import argparse
import random

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

def _get_author_from_article(article: BeautifulSoup) -> str | None:
    """記事要素から投稿者のユーザーIDを取得します。"""
    user_name_div = article.find('div', {'data-testid': 'User-Name'})
    if user_name_div:
        user_link = user_name_div.find('a', {'role': 'link', 'href': lambda href: href and href.startswith('/') and '/status/' not in href})
        if user_link and 'href' in user_link.attrs:
            return user_link['href'].lstrip('/')
    return None

def _get_replying_to_users_from_article(article: BeautifulSoup) -> list[str]:
    """記事要素から返信先のユーザーIDリストを取得します。"""
    users = []
    # csv_generator.pyで使われているセレクタを再利用
    reply_context_element = article.find('div', class_=lambda x: x and 'r-4qtqp9' in x and 'r-zl2h9q' in x)
    if reply_context_element:
        links = reply_context_element.find_all('a', {'role': 'link', 'href': lambda href: href and href.startswith('/')})
        for link in links:
            href = link['href']
            if '/status/' not in href:
                user_id = href.lstrip('/')
                if user_id:
                    users.append(user_id)
    return users

# グローバル変数として WebDriver インスタンスを保持
# driver = None # グローバルなdriverはシングルトン管理に移行するため不要

def get_thread_details(tweet_url: str, driver: webdriver.Chrome) -> Tuple[str | None, int | None, bool]:
    """
    指定されたツイートURLから詳細情報を取得します。
    - スレッドの起点となるツイートの投稿者
    - そのツイート自身の現在の返信数
    - 自分が既にそのツイートに返信しているか
    エラーが発生した場合は (None, None, False) を返します。
    """
    try:
        logging.info(f"ツイートページにアクセス中: {tweet_url}")
        driver.get(tweet_url)
        
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
        )
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        tweet_articles = soup.find_all('article', {'data-testid': 'tweet'})
        if not tweet_articles:
            logging.warning("ツイート要素が見つかりませんでした。")
            return None, None, False
            
        # 1. スレッドの起点投稿者を取得 (通常はページの最初のツイート)
        root_author = _get_author_from_article(tweet_articles[0])
        if root_author:
            logging.info(f"スレッドの起点投稿者を特定しました: {root_author}")

        # 2. 目的のツイートを特定し、その著者と現在の返信数を取得
        current_reply_num = None
        reply_id = tweet_url.split('/')[-1]
        
        target_article = None
        target_article_index = -1
        # ページ上の全ツイートから、URLとIDが一致するものを探してインデックスも取得
        for i, article in enumerate(tweet_articles):
            links = article.find_all('a', href=True)
            for link in links:
                if f'/status/{reply_id}' in link['href']:
                    target_article = article
                    target_article_index = i
                    break
            if target_article:
                break
        
        target_author = None
        if target_article:
            target_author = _get_author_from_article(target_article)
            reply_button = target_article.find('button', {'data-testid': 'reply'})
            if reply_button and 'aria-label' in reply_button.attrs:
                match = re.search(r'(\d+)', reply_button['aria-label'])
                current_reply_num = int(match.group(1)) if match else 0
            else:
                current_reply_num = 0 # ボタンやラベルがなければ0件
            logging.info(f"ツイート({reply_id})の現在の返信数を取得しました: {current_reply_num}件")
        else:
            logging.warning(f"ページ内で目的のツイート({reply_id})が見つかりませんでした。")

        # 3. 自分が既に返信しているかチェック (最適化版)
        has_my_reply = False
        if target_author and target_article_index != -1:
            # チェック対象のリプライより新しいツイート（＝HTMLリストで手前にあるもの）のみをスキャン
            newer_tweets = tweet_articles[:target_article_index]
            logging.info(f"  -> 自分({TARGET_USER})が返信済みか確認するため、新しい {len(newer_tweets)} 件のツイートをスキャンします...")
            for article in newer_tweets:
                article_author = _get_author_from_article(article)
                if article_author == TARGET_USER:
                    # 自分が書いたツイートを発見。それがターゲットへの返信か確認。
                    replying_to_users = _get_replying_to_users_from_article(article)
                    if target_author in replying_to_users:
                        logging.info(f"  -> 発見: 自分({TARGET_USER})がこのツイートの主({target_author})に返信済みです。")
                        has_my_reply = True
                        break
        
        return root_author, current_reply_num, has_my_reply

    except TimeoutException:
        logging.error(f"ページのロード中にタイムアウトしました: {tweet_url}")
        return None, None, False
    except Exception as e:
        logging.error(f"ツイート詳細の取得中に予期せぬエラーが発生しました: {e}", exc_info=True)
        return None, None, False

def check_and_update_thread_origin(replies_data: List[Dict], driver: webdriver.Chrome) -> List[Dict]:
    """
    各リプライのスレッド起点が自分自身かを確認し、'is_my_thread' を更新します。
    """
    updated_replies = []
    
    for reply in replies_data:
        tweet_url = f"https://x.com/{reply['UserID']}/status/{reply['reply_id']}"
        root_author, _, _ = get_thread_details(tweet_url, driver) # 返信数と返信済みフラグはここでは使わない
        
        if root_author and root_author == TARGET_USER:
            reply['is_my_thread'] = True
            logging.info(f"自分のスレッドのリプライ（再判定）: {reply.get('reply_id')}")
        else:
            reply['is_my_thread'] = False
            logging.info(f"他人のスレッドのリプライ（再判定）: {reply.get('reply_id')} (起点: {root_author})")
        
        updated_replies.append(reply)
            
    return updated_replies

def get_priority_replies(replies_data: List[Dict]) -> List[Dict]:
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

def main_process(driver: webdriver.Chrome, input_csv: str, limit: int = None) -> str | None:
    """
    入力CSVを読み込み、スレッドの起点を確認・更新し、結果を一件ずつ新しいCSVに追記します。
    """
    logging.info(f"'{input_csv}' からデータを読み込み、逐次処理を開始します...")
    try:
        df = pd.read_csv(input_csv)

        # 'date_time' 列で昇順にソートする処理を追加
        if 'date_time' in df.columns:
            # datetimeオブジェクトに変換（不正な形式はNaT）
            df['date_time'] = pd.to_datetime(df['date_time'], errors='coerce')
            # NaTを持つ行を削除
            df.dropna(subset=['date_time'], inplace=True)
            # 日付でソート
            df.sort_values(by='date_time', ascending=True, inplace=True)
            logging.info("CSVデータを日付時刻順（昇順）にソートしました。")
        else:
            logging.warning("'date_time' 列が見つからなかったため、ソート処理をスキップしました。")

        # 'contents' 列のNaN（空欄）を空文字列に置換
        if 'contents' in df.columns:
            df['contents'] = df['contents'].fillna('')

        # 'reply_num' を数値に変換し、存在しない場合は0を代入
        if 'reply_num' in df.columns:
            df['reply_num'] = pd.to_numeric(df['reply_num'], errors='coerce').fillna(0).astype(int)
        else:
            df['reply_num'] = 0
            logging.warning("'reply_num'列が見つからなかったため、0として扱います。")

        # ユーザーの指示に従い、reply_numが0の行のみを処理 -> このチェックは古い可能性があるため、リアルタイムチェックに移行
        # original_count = len(df)
        # df = df[df['reply_num'] == 0].copy()
        # logging.info(f"reply_numが0のリプライのみを処理します。{original_count}件から{len(df)}件にフィルタリングしました。")
        logging.info("CSVに記載のreply_numに関わらず、全件を対象にリアルタイムでの返信数チェックを行います。")
        
        if limit:
            df = df.head(limit)
            logging.info(f"処理件数を {limit} 件に制限しました。")
        logging.info(f"CSVから {len(df)} 件のリプライを読み込みました。")
    except FileNotFoundError:
        logging.error(f"入力ファイルが見つかりません: {input_csv}")
        return None
    except Exception as e:
        logging.error(f"CSVファイルの読み込み中にエラーが発生しました: {e}")
        return None

    # 出力ファイルパスの決定
    base_name = os.path.basename(input_csv)
    name_part = base_name.replace('extracted_tweets_', '')
    output_csv = os.path.join("output", f"priority_replies_rechecked_{name_part}")

    # 出力ファイルのヘッダーを準備
    fieldnames = list(df.columns)
    if 'is_my_thread' not in fieldnames:
        fieldnames.append('is_my_thread')

    # driverは外部から渡されるので、ここでは初期化しない
    try:
        if not driver:
            logging.error("有効なWebDriverインスタンスが渡されませんでした。")
            return None

        # 最初にヘッダーをファイルに書き込む (wモードでファイルを初期化)
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

        logging.info(f"--- スレッド起点の確認とCSVへの逐次書き込みを開始します ({output_csv}) ---")
        
        processed_count = 0
        # DataFrameを行ごとに処理
        for index, row in df.iterrows():
            reply_dict = row.to_dict()
            tweet_url = f"https://x.com/{reply_dict['UserID']}/status/{reply_dict['reply_id']}"
            
            logging.info(f"[{index + 1}/{len(df)}] 処理中: {tweet_url}")

            # 安定性向上のため、リクエスト間にランダムな待機時間を挿入
            sleep_time = round(random.uniform(2, 5), 1)
            logging.info(f"  -> {sleep_time}秒待機...")
            time.sleep(sleep_time)
            
            root_author, current_reply_num, has_my_reply = get_thread_details(tweet_url, driver)
            
            # 詳細が取得できなかった場合はスキップ
            if root_author is None and current_reply_num is None:
                logging.warning(f"  -> ツイート詳細を取得できなかったため、スキップします。")
                continue

            # 自分が既に返信している場合はスキップ
            if has_my_reply:
                logging.info(f"  -> 自分が既に返信済みのため、このリプライはスキップします。")
                continue

            # 最新の返信数をチェックし、1以上ならスキップ
            if current_reply_num is not None and current_reply_num > 0:
                logging.info(f"  -> 最新の返信数が {current_reply_num} 件のため、このリプライはスキップします。")
                continue
            
            # is_my_thread フラグと最新の返信数を更新
            is_my_thread = (root_author and root_author == TARGET_USER)
            reply_dict['is_my_thread'] = is_my_thread
            reply_dict['reply_num'] = current_reply_num if current_reply_num is not None else 0 # Noneの場合は0にフォールバック
            
            if is_my_thread:
                logging.info(f"  -> 自分のスレッドのリプライです。")
            else:
                logging.info(f"  -> 他人のスレッドのリプライです。(起点: {root_author})")

            # 追記モードでファイルを開き、1行書き込む
            with open(output_csv, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(reply_dict)
            
            processed_count += 1

        logging.info(f"--- 全 {processed_count} 件の処理が完了し、{output_csv} に保存されました ---")
        return output_csv

    except Exception as e:
        logging.error(f"処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        return None
    # finallyブロックは呼び出し元でdriverを閉じるため、ここでは何もしない

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
    
    # is_my_threadを再評価
    driver = None
    try:
        driver = setup_driver(headless=False)
        if not driver:
            return
            
        updated_replies = check_and_update_thread_origin(replies_data[:5], driver)
        
        # 優先度フィルタリングは行わない
        # priority_replies = get_priority_replies(updated_replies, driver)

        # 結果を新しいCSVファイルに出力
        base_name = os.path.basename(input_csv)
        name_part = base_name.replace('extracted_tweets_', '').replace('.csv', '')
        output_csv_path = os.path.join("output", f"test_rechecked_{name_part}.csv")
        
        write_replies_to_csv(updated_replies, output_csv_path)

    except Exception as e:
        logging.error(f"テスト処理中にエラーが発生しました: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="CSV内のリプライのスレッド起点と最新の返信数を確認・更新します。")
    parser.add_argument("input_csv", help="入力CSVファイルのパス")
    parser.add_argument("--limit", type=int, default=None, help="処理するリプライの最大数")
    parser.add_argument("--test", action="store_true", help="テストモードで実行（先頭5件のみ処理）")
    args = parser.parse_args()

    # 単体実行時のみ、driverの起動と終了をここで行う
    driver = None
    try:
        # ユーザーの記憶に基づき、デバッグ中はFalseを維持 [[memory:2213753]]
        driver = setup_driver(headless=False)
        if driver:
            if args.test:
                main_test(args.input_csv)
            else:
                main_process(driver, args.input_csv, args.limit)
    finally:
        if driver:
            driver.quit()
            logging.info("Selenium WebDriverを終了しました。") 