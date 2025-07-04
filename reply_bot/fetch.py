import json
import logging
import os
from datetime import datetime, timedelta, timezone
import time
import re
import csv
import pytz
import pickle

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException

from .config import TARGET_USER
from .get_cookie import load_cookies_and_navigate # load_cookies_and_navigate をインポート

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# JSTタイムゾーンを定義
jst = pytz.timezone('Asia/Tokyo')

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
        content = content_element.get_text(separator='\n') if content_element else ""

        # リプライしたユーザーIDと表示名の抽出
        replier_id = ""
        display_name = ""
        user_name_div = tweet_article.find('div', {'data-testid': 'User-Name'})
        if user_name_div:
            display_name_span = user_name_div.find('span', class_=lambda x: x and 'r-dnmrzs' in x and 'r-1udh08x' in x and 'r-1udbk01' in x and 'r-3s2u2q' in x)
            if display_name_span:
                display_name = display_name_span.get_text(separator='').strip()
            
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
            "like_num": like_num
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

def fetch_replies(target_user: str, output_csv_path: str) -> list[dict]:
    """
    Seleniumを使用して、指定ユーザーのツイートに対するリプライを取得します。
    Twitterの通知ページからリプライ一覧を抽出し、スクロールしながらHTMLを保存し、
    重複をスキップしてリプライ情報をCSVにエクスポートします。
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
            WebDriverWait(driver, 30).until( # タイムアウトを30秒に延長
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            logging.info("通知ページがロードされました。")
        except TimeoutException:
            logging.warning("通知ページのロード中にタイムアウトしました。Seleniumは続行します。")

        # ページを下にスクロールしてすべてのツイートをロード
        scroll_count = 0
        while True:
            scroll_count += 1
            logging.info(f"スクロール {scroll_count} 回目...")
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
                        fieldnames = ["UserID", "Name", "date_time", "reply_id", "reply_to", "contents", "reply_num", "like_num"]
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
            if new_height == last_height or scroll_count >= 10: # 10回スクロールしたら停止
                logging.info("ページがこれ以上スクロールできないか、最大スクロール回数に達したため、スクロールを停止します。")
                break
        
        logging.info("すべてのスクロールと抽出が完了しました。")

    except Exception as e:
        logging.error(f"エラーが発生しました: {e}")
    finally:
        if driver:
            driver.quit()
        logging.info("Selenium WebDriverを終了しました。")
    return replies_data

if __name__ == "__main__":
    # テスト実行用のダミーユーザー名
    test_user = "nyukimi_AI" # config.py からインポートするTARGET_USERを使用

    # extracted_tweets.csv のファイル名を生成 (時分秒を含める)
    extracted_tweets_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    extracted_tweets_filepath = os.path.join("output", f"extracted_tweets_{extracted_tweets_timestamp}.csv")

    logging.info(f"ユーザー {test_user} のリプライを取得中... (Selenium)")
    sample_replies = fetch_replies(test_user, extracted_tweets_filepath)
    
    if sample_replies:
        logging.info(f"過去72時間で {len(sample_replies)} 件のリプライを取得しました:")
        # CSVファイル名の生成 (時分秒を含める)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"replies_log_{timestamp}.csv"
        csv_filepath = os.path.join("log", csv_filename) # logフォルダ内に保存

        with open(csv_filepath, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ["tweet_id", "replier_id", "content", "tweet_datetime", "reply_count", "like_count"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for reply in sample_replies:
                # datetimeオブジェクトをISOフォーマット文字列に変換
                reply['tweet_datetime'] = reply['tweet_datetime'].isoformat()
                writer.writerow(reply)
        logging.info(f"リプライログを {csv_filepath} に書き出しました。")

        for reply in sample_replies[:5]: # 最初の5件のみ表示
            logging.info(f"Tweet ID: {reply.get('tweet_id')}, Replier ID: {reply.get('replier_id')}, Content: {reply.get('content')}, Datetime: {reply.get('tweet_datetime')}, Reply Count: {reply.get('reply_count')}, Like Count: {reply.get('like_count')}")
    else:
        logging.info(f"過去72時間で {test_user} のリプライは見つかりませんでした。") 