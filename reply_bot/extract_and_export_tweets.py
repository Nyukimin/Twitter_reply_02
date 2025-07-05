import logging
from bs4 import BeautifulSoup
import os
import json
from datetime import datetime, timedelta, timezone
import time
import re
import csv
import pytz
import pickle

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

jst = pytz.timezone('Asia/Tokyo')

def extract_tweet_info(tweet_article: BeautifulSoup) -> dict | None:
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

        # 言語コードの抽出
        lang = 'und' # デフォルトは 'und'
        if content_element and content_element.has_attr('lang'):
            lang = content_element['lang']

        return {
            "UserID": replier_id,
            "Name": display_name,
            "date_time": tweet_datetime_jst.isoformat(), # JSTに変換してISOフォーマットで文字列として保存
            "reply_id": reply_id,
            "reply_to": reply_to_user,
            "contents": content,
            "reply_num": reply_num,
            "like_num": like_num,
            "lang": lang
        }
    except Exception as e:
        logging.error(f"ツイート情報の抽出中にエラーが発生しました: {e}")
        return None

def extract_and_export_tweets_to_csv(html_file_path: str, output_csv_path: str, limit: int = 10):
    """
    HTMLファイルからツイート要素を抽出し、CSVファイルに書き出します。
    """
    all_extracted_data = []
    try:
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        soup = BeautifulSoup(html_content, 'html.parser')
        tweets = soup.find_all('article', {'data-testid': 'tweet'})
        
        logging.info(f"{len(tweets)} 個のツイート要素が見つかりました。最初の {limit} 個を処理します。")

        for i, tweet_article in enumerate(tweets):
            if i >= limit:
                break
            extracted_info = extract_tweet_info(tweet_article)
            if extracted_info:
                all_extracted_data.append(extracted_info)
            
        if all_extracted_data:
            fieldnames = ["UserID", "Name", "date_time", "reply_id", "reply_to", "contents", "reply_num", "like_num", "lang"]
            with open(output_csv_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_extracted_data)
            logging.info(f"抽出されたツイート情報を {output_csv_path} に書き出しました。")
        else:
            logging.warning("抽出されたツイート情報がありませんでした。CSVファイルは作成されません。")

    except FileNotFoundError:
        logging.error(f"Error: {html_file_path} が見つかりません。")
    except Exception as e:
        logging.error(f"ファイルの読み込みまたは解析中にエラーが発生しました: {e}")

if __name__ == "__main__":
    # プロジェクトルートからの相対パスで指定
    html_source_file = "debug_page_source.html"
    output_csv_file = "extracted_tweets.csv"
    extract_and_export_tweets_to_csv(html_source_file, output_csv_file, limit=10) 