import json
import logging
import os
from datetime import datetime, timedelta, timezone
import time
import re
import csv
import pytz
import argparse
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup, NavigableString, Tag
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .config import TARGET_USER, MAX_SCROLLS, LOGIN_TIMEOUT_ENABLED, LOGIN_TIMEOUT_SECONDS, PAGE_LOAD_TIMEOUT_SECONDS
from .utils import setup_driver # 共通のWebDriverセットアップをインポート

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# JSTタイムゾーンを定義
jst = pytz.timezone('Asia/Tokyo')

def extract_text_with_emoji(element) -> str:
    """
    BeautifulSoup要素からテキストとimgタグのalt属性（絵文字）を含めて抽出する
    """
    if element is None:
        return ""
    result = ""
    for child in element.children:
        if isinstance(child, NavigableString):
            result += str(child)
        elif isinstance(child, Tag):
            if child.name == "img" and child.has_attr("alt"):
                result += child["alt"]
            else:
                result += extract_text_with_emoji(child)
    return result

def _extract_tweet_info(tweet_article: BeautifulSoup) -> dict | None:
    """
    BeautifulSoupのtweet_article要素からツイート情報を抽出します。
    """
    try:
        # ツイートID（リプライ自身のID）の抽出
        reply_link_element = tweet_article.find('a', {'href': lambda href: href and '/status/' in href})
        reply_full_url = reply_link_element['href'] if reply_link_element else None
        
        reply_id = None
        if reply_full_url:
            reply_id = reply_full_url.split('/')[-1]

        if not reply_id or not reply_id.isdigit():
            logging.warning("有効なリプライIDが見つかりませんでした。スキップします。")
            return None

        # リプライ本文の抽出
        content_element = tweet_article.find('div', {'data-testid': 'tweetText'})
        content = extract_text_with_emoji(content_element) if content_element else ""

        # リプライしたユーザーIDと表示名の抽出
        replier_id = ""
        display_name = ""
        user_name_div = tweet_article.find('div', {'data-testid': 'User-Name'})
        if user_name_div:
            display_name_span = user_name_div.find('span', class_=lambda x: x and 'r-dnmrzs' in x and 'r-1udh08x' in x and 'r-1udbk01' in x and 'r-3s2u2q' in x)
            if display_name_span:
                display_name = extract_text_with_emoji(display_name_span).strip()
            
            user_link = user_name_div.find('a', {'role': 'link', 'href': lambda href: href and href.startswith('/') and '/status/' not in href})
            if user_link and 'href' in user_link.attrs:
                replier_id = user_link['href'].lstrip('/')

        if not replier_id:
            logging.warning(f"リプライしたユーザーIDが見つかりませんでした。スキップします。リプライID: {reply_id}")
            return None

        # ツイート投稿日時の抽出 (timeタグのdatetime属性) とJST変換
        time_element = tweet_article.find('time')
        tweet_datetime_utc = None
        tweet_datetime_jst = None
        if time_element and 'datetime' in time_element.attrs:
            try:
                tweet_datetime_utc = datetime.strptime(time_element['datetime'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
                tweet_datetime_jst = tweet_datetime_utc.astimezone(jst)
            except ValueError as e:
                logging.warning(f"日時解析エラー: {e} - datetime属性: {time_element['datetime']}")
                return None
        
        if not tweet_datetime_jst:
            logging.warning("ツイート投稿日時が見つかりませんでした。スキップします。")
            return None

        # リプライ対象ユーザーIDの抽出
        reply_to_user = None
        reply_context_element = tweet_article.find('div', class_=lambda x: x and 'r-4qtqp9' in x and 'r-zl2h9q' in x)
        if reply_context_element:
            reply_to_link = reply_context_element.find('a', {'href': lambda href: href and href.startswith('/') and '/status/' not in href})
            if reply_to_link and 'href' in reply_to_link.attrs:
                reply_to_user = reply_to_link['href'].lstrip('/')

        # スレッド起点判定
        is_my_thread = False
        if reply_to_user:
            # リプライ元がMaya（@Maya19960330）かどうかを判定
            is_my_thread = (reply_to_user == "Maya19960330")
            logging.info(f"リプライ元ユーザー: {reply_to_user}, スレッド起点判定: {is_my_thread}")

        # 返信数といいね数の抽出
        reply_num = 0
        like_num = 0
        
        reply_button = tweet_article.find('button', {'data-testid': 'reply'})
        if reply_button and 'aria-label' in reply_button.attrs:
            match = re.search(r'(\d+)\s*件の返信', reply_button['aria-label'])
            if match:
                reply_num = int(match.group(1))
        
        like_button = tweet_article.find('button', {'data-testid': 'like'})
        if like_button and 'aria-label' in like_button.attrs:
            match = re.search(r'(\d+)\s*件のいいね', like_button['aria-label'])
            if match:
                like_num = int(match.group(1))

        return {
            "UserID": replier_id,
            "Name": display_name,
            "date_time": tweet_datetime_jst.isoformat(), # JSTに変換してISOフォーマットで文字列として保存
            "reply_id": reply_id,
            "reply_to": reply_to_user,
            "contents": content,
            "reply_num": reply_num,
            "like_num": like_num,
            "is_my_thread": is_my_thread  # スレッド起点判定フラグを追加
        }
    except Exception as e:
        logging.error(f"ツイート情報の抽出中にエラーが発生しました: {e}")
        return None

def main_process(output_csv_path: str, max_scrolls: int = MAX_SCROLLS) -> str | None:
    """
    Seleniumを使用して、指定ユーザーのツイートに対するリプライを取得し、CSVリストを生成します。
    Twitterの通知ページからリプライ一覧を抽出し、スクロールしながらHTMLを保存し、
    重複をスキップしてリプライ情報をCSVにエクスポートします。
    
    Args:
        output_csv_path: 出力CSVファイルパス
        max_scrolls: 最大スクロール回数（デフォルト: 100）
    
    Returns:
        str | None: 生成されたCSVファイルのパス。失敗した場合はNone。
    """
    # 出力ディレクトリの作成
    output_dir = os.path.dirname(output_csv_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    replies_data = []
    processed_reply_ids = set()
    csv_header_written = False

    # CSVファイルが既に存在する場合はヘッダーを書き込まない (追記モード)
    if os.path.exists(output_csv_path):
        with open(output_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            if next(reader, None): # ヘッダー行を読み飛ばす
                csv_header_written = True

    driver = None
    try:
        driver = setup_driver(headless=False) # 動作確認のためヘッドフルで実行
        if not driver:
            logging.error("WebDriverのセットアップに失敗しました。")
            return None

        # 通知ページにアクセス
        logging.info("通知ページにアクセス中: https://x.com/notifications/mentions")
        driver.get("https://x.com/notifications/mentions")

        # ページが完全にロードされるのを待機するために明示的な待機を追加
        try:
            if LOGIN_TIMEOUT_ENABLED:
                logging.info(f"ログインタイムアウト設定: {LOGIN_TIMEOUT_SECONDS}秒")
                WebDriverWait(driver, LOGIN_TIMEOUT_SECONDS).until(
                    EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
                )
                logging.info("通知ページがロードされました。")
            else:
                logging.info("ログインタイムアウトが無効化されています。ページロードを待機しません。")
        except TimeoutException:
            if LOGIN_TIMEOUT_ENABLED:
                logging.warning(f"通知ページのロード中にタイムアウトしました（{LOGIN_TIMEOUT_SECONDS}秒）。Seleniumは続行します。")
            else:
                logging.info("ログインタイムアウトが無効化されているため、タイムアウトは発生しません。")

        # 0ページ目（初回ページ）のデータ取得
        logging.info("0ページ目（初回ページ）のデータ取得を開始します...")
        time.sleep(5)  # 初回ページの完全ロードを待機
        
        # 0ページ目のHTMLソースを保存
        initial_html_source = driver.page_source
        debug_html_file_path = "source/debug_page_source_000.html"
        with open(debug_html_file_path, "w", encoding="utf-8") as f:
            f.write(initial_html_source)
        logging.info(f"0ページ目のページソースを {debug_html_file_path} に保存しました。")

        # 0ページ目のツイート要素を抽出
        soup = BeautifulSoup(initial_html_source, 'html.parser')
        initial_tweets = soup.find_all('article', {'data-testid': 'tweet'})
        logging.info(f"0ページ目から {len(initial_tweets)} 個のツイート要素を検出しました。")

        # 0ページ目のデータ抽出とCSV出力
        for tweet_article in initial_tweets:
            extracted_info = _extract_tweet_info(tweet_article)
            if extracted_info:
                reply_id = extracted_info.get("reply_id")
                if reply_id and reply_id not in processed_reply_ids:
                    replies_data.append(extracted_info)
                    processed_reply_ids.add(reply_id)

                    # CSVに書き込む (追記モード)
                    fieldnames = ["UserID", "Name", "date_time", "reply_id", "reply_to", "contents", "reply_num", "like_num", "is_my_thread"]
                    with open(output_csv_path, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        if not csv_header_written:
                            writer.writeheader()
                            csv_header_written = True
                        writer.writerow(extracted_info)
                elif reply_id:
                    logging.info(f"重複するリプライIDをスキップしました: {reply_id}")

        logging.info("0ページ目のデータ取得が完了しました。")

        # ページを下にスクロールしてすべてのツイートをロード
        scroll_count = 0
        while True:
            scroll_count += 1
            logging.info(f"スクロール {scroll_count}/{max_scrolls} 回目...")
            current_html_source = driver.page_source
            
            # 各スクロール後にHTMLソースを連番で保存
            debug_html_file_path = f"source/debug_page_source_{scroll_count:03d}.html"
            with open(debug_html_file_path, "w", encoding="utf-8") as f:
                f.write(current_html_source)
            logging.info(f"現在のページソースを {debug_html_file_path} に保存しました。")

            soup = BeautifulSoup(current_html_source, 'html.parser')
            tweets = soup.find_all('article', {'data-testid': 'tweet'})
            logging.info(f"HTMLファイルから {len(tweets)} 個のツイート要素を検出しました。")

            # 抽出とCSV出力
            for tweet_article in tweets:
                extracted_info = _extract_tweet_info(tweet_article)
                if extracted_info:
                    reply_id = extracted_info.get("reply_id")
                    if reply_id and reply_id not in processed_reply_ids:
                        replies_data.append(extracted_info)
                        processed_reply_ids.add(reply_id)

                        # CSVに書き込む (追記モード)
                        fieldnames = ["UserID", "Name", "date_time", "reply_id", "reply_to", "contents", "reply_num", "like_num", "is_my_thread"]
                        with open(output_csv_path, 'a', newline='', encoding='utf-8') as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                            if not csv_header_written:
                                writer.writeheader()
                                csv_header_written = True
                            writer.writerow(extracted_info)
                    elif reply_id:
                        logging.info(f"重複するリプライIDをスキップしました: {reply_id}")
            
            last_height = driver.execute_script("return document.body.scrollHeight")
            window_height = driver.execute_script("return window.innerHeight;")
            scroll_by = window_height * 0.8 # 20%重複するように80%スクロール

            # 現在のスクロール位置から指定量スクロール
            driver.execute_script(f"window.scrollBy(0, {scroll_by});")
            time.sleep(5) # スクロール後のコンテンツロードを待つ (5秒に延長)
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            
            # 新しいコンテンツがロードされなかった場合、または最大スクロール回数に達した場合に停止
            if new_height == last_height or scroll_count >= max_scrolls:
                logging.info(f"ページがこれ以上スクロールできないか、最大スクロール回数({max_scrolls}回)に達したため、スクロールを停止します。")
                break
        
        logging.info("すべてのスクロールと抽出が完了しました。")

    except Exception as e:
        logging.error(f"リプライ取得処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        return None
    finally:
        if driver:
            driver.quit()
            logging.info("Selenium WebDriverを終了しました。")

    # 最終的なCSV書き込み
    if replies_data:
        try:
            with open(output_csv_path, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=replies_data[0].keys())
                if not csv_header_written:
                    writer.writeheader()
                writer.writerows(replies_data)
            logging.info(f"合計 {len(replies_data)} 件のリプライを {output_csv_path} に保存しました。")
            return output_csv_path
        except Exception as e:
            logging.error(f"CSVファイルへの書き込み中にエラーが発生しました: {e}")
            return None
    else:
        logging.info("新しいリプライは見つかりませんでした。")
        # 新しいリプライがなくても、ファイル自体は存在している可能性があるのでパスを返す
        return output_csv_path

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Xの通知ページからリプライを取得し、CSVファイルに出力します。')
    parser.add_argument('output_csv', type=str, help='出力するCSVファイルのパス (例: output/extracted_tweets.csv)')
    
    args = parser.parse_args()
    
    main_process(args.output_csv) 