import json
import logging
import os
from datetime import datetime, timedelta, timezone
import time
import re

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

from .config import TARGET_USER
from .get_cookie import load_cookies_and_navigate # load_cookies_and_navigate をインポート

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_tweet_content(tweet_id: str) -> str | None:
    """
    今回はSeleniumベースで実装するため、この関数は直接使用されませんが、
    将来的にはツイート詳細ページからコンテンツを取得するロジックをここに追加可能です。
    現時点では None を返します。
    """
    return None

def fetch_replies(target_user: str) -> list[dict]:
    """
    Seleniumを使用して、指定ユーザーのツイートに対するリプライを取得します。
    Twitterの通知ページからリプライ一覧を抽出し、スレッドの起点判定も行います。
    """
    replies_data = []
    driver = None
    try:
        options = Options()
        options.add_argument('--headless') # ヘッドレスモードで実行
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        logging.info("Selenium WebDriverを起動しました。")

        # Cookieを読み込んでログイン状態を復元
        if not load_cookies_and_navigate(driver):
            logging.error("Cookieの読み込みに失敗しました。手動ログインが必要です。")
            return []
        
        logging.info("Cookieを使ってXにログインしました。")

        # 通知ページへ移動
        notification_url = f"https://x.com/notifications/mentions"
        driver.get(notification_url)
        logging.info(f"通知ページ ({notification_url}) にアクセスしました。")
        logging.info(f"現在のURL: {driver.current_url}")
        logging.info(f"ページタイトル: {driver.title}")

        # ページが完全にロードされるのを待機 (例: タイムラインのツイートが表示されるまで)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
        )
        logging.info("通知ページのコンテンツがロードされました。")

        # デバッグ用にページソースをファイルに保存
        with open("debug_page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logging.info("現在のページソースを debug_page_source.html に保存しました。")

        # ページソースを取得してBeautifulSoupで解析
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # リプライ要素の抽出 (XのHTML構造は頻繁に変わるため、要調整)
        # 仮のセレクタ。実際には開発者ツールで正確なセレクタを特定する必要がある
        # 例えば、特定の属性やクラスを持つarticleタグを探す
        tweets = soup.find_all('article', {'data-testid': 'tweet'})

        if not tweets:
            logging.warning("data-testid=\"tweet\"を持つarticleタグが見つかりませんでした。ページソースを確認してください。")
            logging.info(f"取得したページソースの一部: {driver.page_source[:1000]}...") # ページソースの先頭1000文字を出力

        now = datetime.now(timezone.utc)
        twenty_four_hours_ago = now - timedelta(hours=24)

        for tweet_article in tweets:
            try:
                # ツイートID（リプライ自身のID）の抽出
                # 各ツイートの permalink を含む a タグを探す
                # data-testid="tweet" の中にあり、href属性が /<user>/status/<id> の形式
                tweet_link = tweet_article.find('a', {'href': lambda href: href and '/status/' in href and '/photo/' not in href and '/video/' not in href})
                
                reply_id = None
                if tweet_link and 'href' in tweet_link.attrs:
                    reply_id = tweet_link['href'].split('/')[-1]

                if not reply_id or not reply_id.isdigit():
                    logging.warning("有効なリプライIDが見つかりませんでした。スキップします。")
                    continue

                # リプライ本文の抽出
                content_element = tweet_article.find('div', {'data-testid': 'tweetText'})
                content = content_element.get_text(separator='\n') if content_element else ""

                # リプライしたユーザーIDの抽出を強化
                replier_id = ""
                # まずは data-testid="User-Names" からの抽出を試みる (現在の実装)
                user_names_div = tweet_article.find('div', {'data-testid': 'User-Names'})
                if user_names_div:
                    user_link = user_names_div.find('a', {'href': lambda href: href and href.startswith('/') and '/status/' not in href})
                    if user_link and 'href' in user_link.attrs:
                        replier_id = user_link['href'].lstrip('/')
                
                # 見つからない場合は、より一般的なユーザープロフィールリンクを探す
                if not replier_id:
                    # ツイート記事内で直接ユーザーのプロフィールリンクを探す
                    # 例: <a role="link" href="/username" ...>
                    user_profile_link = tweet_article.find('a', {'role': 'link', 'href': lambda href: href and href.startswith('/') and '/status/' not in href})
                    if user_profile_link and 'href' in user_profile_link.attrs:
                        replier_id = user_profile_link['href'].lstrip('/')

                if not replier_id:
                    logging.warning(f"リプライしたユーザーIDが見つかりませんでした。スキップします。リプライID: {reply_id}")
                    continue

                # リプライの言語はBeautifulSoupでは直接取得が難しい場合が多いので、仮で日本語と設定
                lang = "ja"

                # 元ツイートのコンテンツ (ここではまだ取得しないが、Placeholderとして追加)
                original_tweet_content = None

                # ツイート投稿日時の抽出 (timeタグのdatetime属性)
                time_element = tweet_article.find('time')
                tweet_datetime = None
                if time_element and 'datetime' in time_element.attrs:
                    try:
                        # %Y-%m-%dT%H:%M:%S.%fZ はISO 8601形式で、ZはUTCを意味する
                        # timezone.utc を明示的に設定してawareなdatetimeオブジェクトにする
                        tweet_datetime = datetime.strptime(time_element['datetime'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
                    except ValueError as e:
                        logging.warning(f"日時解析エラー: {e} - datetime属性: {time_element['datetime']}")
                        continue

                if not tweet_datetime:
                    logging.warning("ツイート投稿日時が見つかりませんでした。スキップします。")
                    continue
                
                # 24時間以上前のリプライはスキップ
                if tweet_datetime < twenty_four_hours_ago:
                    logging.info(f"24時間以上前のリプライです。スキップします。リプライID: {reply_id}")
                    continue

                # スレッド起点判定ロジックを強化
                is_my_thread = False
                reply_context_element = tweet_article.find('div', {'data-testid': 'replyContext'})
                if reply_context_element:
                    # replyContext 内のユーザーリンクを探す
                    target_user_link_in_context = reply_context_element.find('a', {'href': f'/{target_user}'})
                    if target_user_link_in_context:
                        is_my_thread = True
                
                # もし replyContext で見つからない場合、リプライ本文に自分のユーザー名が含まれているかチェック
                if not is_my_thread and target_user.lower() in content.lower():
                    is_my_thread = True

                # リプライの言語 (BeautifulSoupでは直接取得が難しい場合が多い。後で推定するか、PlaywrightのJS実行で取得)
                lang = "ja" # 仮で日本語と設定

                replies_data.append({
                    "tweet_id": reply_id,
                    "reply_id": reply_id, # リプライ自身のID
                    "content": content,
                    "replier_id": replier_id,
                    "lang": lang,
                    "original_tweet_content": original_tweet_content, # 現時点では None
                    "is_my_thread": is_my_thread
                })
            except Exception as e:
                logging.error(f"ツイートの解析中にエラーが発生しました: {e}")
                if tweet_article:
                    logging.error(f"解析失敗したツイートのHTMLスニペット: {tweet_article.prettify()[:500]}...") # 失敗したツイートのHTMLスニペットを出力

    except Exception as e:
        logging.error(f"リプライ収集中にエラーが発生しました: {e}")
    finally:
        if driver:
            driver.quit()

    return replies_data

if __name__ == "__main__":
    # テスト実行用のダミーユーザー名
    test_user = "nyukimi_AI" # config.py からインポートするTARGET_USERを使用

    logging.info(f"ユーザー {test_user} のリプライを取得中... (Selenium)")
    sample_replies = fetch_replies(test_user)
    
    if sample_replies:
        logging.info(f"過去24時間で {len(sample_replies)} 件のリプライを取得しました:")
        for reply in sample_replies[:5]: # 最初の5件のみ表示
            logging.info(reply)
    else:
        logging.info(f"過去24時間で {test_user} のリプライは見つかりませんでした。") 