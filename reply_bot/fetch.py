import json
import logging
import os
from datetime import datetime, timedelta, timezone
import time
import re
import csv
import pytz
import pickle
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup, NavigableString, Tag
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .config import TARGET_USER, MAX_SCROLLS, LOGIN_TIMEOUT_ENABLED, LOGIN_TIMEOUT_SECONDS, PAGE_LOAD_TIMEOUT_SECONDS
from .get_cookie import load_cookies_and_navigate # load_cookies_and_navigate をインポート
from . import db  # データベースモジュールをインポート

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

def fetch_tweet_content(tweet_id: str) -> str | None:
    """
    今回はSeleniumベースで実装するため、この関数は直接使用されませんが、
    将来的にはツイート詳細ページからコンテンツを取得するロジックをここに追加可能です。
    現時点では None を返します。
    """
    return None

def fetch_replies(target_user: str, output_csv_path: str, max_scrolls: int = MAX_SCROLLS) -> list[dict]:
    """
    Seleniumを使用して、指定ユーザーのツイートに対するリプライを取得します。
    Twitterの通知ページからリプライ一覧を抽出し、スクロールしながらHTMLを保存し、
    重複をスキップしてリプライ情報をCSVにエクスポートします。
    
    Args:
        target_user: 対象ユーザー名
        output_csv_path: 出力CSVファイルパス
        max_scrolls: 最大スクロール回数（デフォルト: 100）
    """
    replies_data = []
    processed_reply_ids = set()
    csv_header_written = False
    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # output_csv_path = f"output/extracted_tweets_{timestamp}.csv" # CSV出力パスを定義

    # CSVファイルが既に存在する場合はヘッダーを書き込まない (追記モード)
    if os.path.exists(output_csv_path):
        with open(output_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            if next(reader, None): # ヘッダー行を読み飛ばす
                csv_header_written = True

    driver = None
    try:
        # WebDriverのセットアップ
        options = webdriver.ChromeOptions()
        # options.add_argument('--headless')  # デバッグのため一時的にコメントアウト
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--log-level=3') # INFOレベル以上のログのみ表示
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # ページ読み込みタイムアウトを設定
        if LOGIN_TIMEOUT_ENABLED:
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
            logging.info(f"ページ読み込みタイムアウト設定: {PAGE_LOAD_TIMEOUT_SECONDS}秒")
        else:
            logging.info("ページ読み込みタイムアウトが無効化されています。")
        
        logging.info("Selenium WebDriverを起動しました。")

        # Cookieを読み込み、ブラウザにセットします
        logging.info("Cookieを読み込み、ブラウザにセットします")
        cookie_file_path = os.path.join('cookie', 'twitter_cookies_01.pkl')
        if os.path.exists(cookie_file_path):
            with open(cookie_file_path, 'rb') as f:
                cookies = pickle.load(f)
            # ドメインを指定してCookieを追加
            driver.get("https://x.com/") # ドメインにアクセスしてCookieを設定できるようにする
            for cookie in cookies:
                # Seleniumに設定する前に、'expiry'キーを削除または変換する
                if 'expiry' in cookie: # datetimeオブジェクトをタイムスタンプに変換
                    cookie['expiry'] = int(cookie['expiry']) if isinstance(cookie['expiry'], datetime) else cookie['expiry']
                driver.add_cookie(cookie)
            logging.info("Cookieをブラウザにセットしました。")
        else:
            logging.warning("Cookieファイルが見つかりません。ログインなしで続行します。")

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
        logging.error(f"エラーが発生しました: {e}")
    finally:
        if driver:
            driver.quit()
        logging.info("Selenium WebDriverを終了しました。")
    return replies_data

def main(max_scrolls: int = MAX_SCROLLS):
    """
    メイン実行関数
    
    Args:
        max_scrolls: 最大スクロール回数（デフォルト: 100）
    """
    # データベース初期化
    db.init_db()
    
    # ログ設定
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('log/fetch.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    # 出力ディレクトリの作成
    output_dir = Path('output')
    output_dir.mkdir(exist_ok=True)
    
    # CSVファイル名の生成（実行開始時）
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_csv_path = output_dir / f'extracted_tweets_{timestamp}.csv'
    
    # fetch_replies関数を呼び出してリプライを取得
    replies = fetch_replies(TARGET_USER, str(output_csv_path), max_scrolls)
    
    # ログファイルの生成
    if replies:
        log_dir = Path('log')
        log_dir.mkdir(exist_ok=True)
        csv_filepath = log_dir / f'replies_log_{timestamp}.csv'
        fieldnames = ["reply_id", "UserID", "Name", "date_time", "reply_to", "contents", "reply_num", "like_num", "is_my_thread"]
        with open(csv_filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for reply in replies:
                writer.writerow(reply)
        for reply in replies[:5]:
            logging.info(f"Reply ID: {reply.get('reply_id')}, User ID: {reply.get('UserID')}, Name: {reply.get('Name')}, Content: {reply.get('contents')}, DateTime: {reply.get('date_time')}, Reply Count: {reply.get('reply_num')}, Like Count: {reply.get('like_num')}, Is My Thread: {reply.get('is_my_thread')}")
    else:
        logging.info(f"過去72時間で {TARGET_USER} のリプライは見つかりませんでした。")

if __name__ == "__main__":
    main() 