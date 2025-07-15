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
from selenium import webdriver

from .config import TARGET_USER, MAX_SCROLLS, LOGIN_TIMEOUT_ENABLED, LOGIN_TIMEOUT_SECONDS, PAGE_LOAD_TIMEOUT_SECONDS, SCROLL_PIXELS
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

        # 返信数が0より大きいツイートはスキップ
        if reply_num > 0:
            logging.info(f"返信数が0より大きいためスキップします: reply_id={reply_id}, reply_num={reply_num}")
            return None

        # 言語コードの抽出
        lang = 'und' # デフォルトは 'und'
        if content_element and content_element.has_attr('lang'):
            lang = content_element['lang']

        # 全ての文字列フィールドがNoneでないことを保証する
        final_replier_id = replier_id if replier_id is not None else ""
        final_display_name = display_name if display_name is not None else ""
        final_reply_to_user = reply_to_user if reply_to_user is not None else ""
        final_content = content if content is not None else ""

        return {
            "UserID": final_replier_id,
            "Name": final_display_name,
            "date_time": tweet_datetime_jst.isoformat(), # JSTに変換してISOフォーマットで文字列として保存
            "reply_id": reply_id,
            "reply_to": final_reply_to_user,
            "contents": final_content,
            "reply_num": reply_num,
            "like_num": like_num,
            "is_my_thread": is_my_thread,
            "lang": lang
        }
    except Exception as e:
        logging.error(f"ツイート情報の抽出中にエラーが発生しました: {e}")
        return None

def main_process(driver: webdriver.Chrome, output_csv_path: str, max_scrolls: int = MAX_SCROLLS, scroll_pixels: int = SCROLL_PIXELS, hours_to_collect: int | None = None) -> str | None:
    """
    Seleniumを使用して、指定ユーザーのツイートに対するリプライを取得し、CSVリストを生成します。
    Twitterの通知ページからリプライ一覧を抽出し、スクロールしながらHTMLを保存し、
    重複をスキップしてリプライ情報をCSVにエクスポートします。
    
    Args:
        driver: SeleniumのWebDriverインスタンス
        output_csv_path: 出力CSVファイルパス
        max_scrolls: 最大スクロール回数
        scroll_pixels: 1回のスクロール量（ピクセル数）
        hours_to_collect: 何時間前までのリプライを収集するか。Noneの場合は制限なし。
    
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

    # 時間の閾値設定
    time_threshold = None
    if hours_to_collect is not None:
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        time_threshold = now - timedelta(hours=hours_to_collect)
        logging.info(f"{hours_to_collect}時間前までのリプライを収集します。閾値: {time_threshold.strftime('%Y-%m-%d %H:%M:%S')}")

    # CSVファイルが既に存在する場合はヘッダーを書き込まない (追記モード)
    if os.path.exists(output_csv_path):
        with open(output_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            if next(reader, None): # ヘッダー行を読み飛ばす
                csv_header_written = True

    stop_processing = False # 処理停止フラグ
    try:
        if not driver:
            logging.error("有効なWebDriverインスタンスが渡されませんでした。")
            return None

        # ユーザーの指示に基づき、強制的に最新情報を取得するナビゲーションシーケンス
        logging.info("--- 最新情報を確実に取得するため、特別なナビゲーションを開始します ---")
        try:
            # 1. home
            logging.info("[1/5] ホームページにアクセスします...")
            driver.get("https://x.com/home")
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            logging.info("ホームページの読み込み完了。")

            # 2. notifications
            logging.info("[2/5] 通知ページにアクセスします...")
            driver.get("https://x.com/notifications")
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            logging.info("通知ページの読み込み完了。")

            # 3. notifications/mentions
            logging.info("[3/5] 通知（メンション）ページにアクセスします...")
            driver.get("https://x.com/notifications/mentions")
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            logging.info("通知（メンション）ページの読み込み完了。")
            time.sleep(5)  # 完全ロードを待機

            # 4. notifications/mentions (again)
            logging.info("[4/5] 再度、通知（メンション）ページにアクセスします...")
            driver.get("https://x.com/notifications/mentions")
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            # 4. notifications (again)
            logging.info("[4/5] 再度、通知ページにアクセスします...")
            driver.get("https://x.com/notifications")
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            logging.info("再度、通知ページの読み込み完了。")

            # 5. notifications/mentions (final)
            logging.info("[5/5] 最終的に通知（メンション）ページにアクセスします...")
            driver.get("https://x.com/notifications/mentions")
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            logging.info("最終的な通知（メンション）ページの読み込み完了。")
            
            # 最新データを確実に取得するため、更新処理を実行
            logging.info("最新データ取得のためページの更新処理を実行します...")
            driver.refresh()
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT_SECONDS).until(
                EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]'))
            )
            logging.info("ページ更新完了。")
            
            # 複数回の軽いスクロールで最新ツイートを確実に読み込む
            logging.info("最新ツイートを確実に読み込むため、複数回のスクロールを実行します...")
            for i in range(3):
                logging.info(f"初期スクロール {i+1}/3 回目...")
                driver.execute_script("window.scrollTo(0, 0);")  # 最上部に移動
                time.sleep(2)
                driver.execute_script("window.scrollBy(0, 500);")  # 軽くスクロール
                time.sleep(2)
                driver.execute_script("window.scrollBy(0, -500);")  # 元に戻す
                time.sleep(2)
            
            logging.info("最新ツイート確認のための最終待機中...")
            time.sleep(10)  # 最新ツイートの完全ロードを待機
            
        except TimeoutException:
            logging.error(f"ナビゲーションシーケンス中にタイムアウトが発生しました（{PAGE_LOAD_TIMEOUT_SECONDS}秒）。処理を中断します。")
            return None
        
        logging.info("--- ナビゲーション完了。リプライの取得を開始します ---")

        # 0ページ目（初回ページ）のデータ取得
        logging.info("0ページ目（初回ページ）のデータ取得を開始します...")
        
        # 最新ツイートが確実に表示されるまで待機とチェック
        logging.info("最新ツイートの表示を確認中...")
        max_wait_attempts = 10
        for attempt in range(max_wait_attempts):
            time.sleep(3)
            current_source = driver.page_source
            soup_check = BeautifulSoup(current_source, 'html.parser')
            tweets_check = soup_check.find_all('article', {'data-testid': 'tweet'})
            
            if tweets_check:
                # 最初のツイートの時刻を確認
                first_tweet_info = _extract_tweet_info(tweets_check[0])
                if first_tweet_info:
                    first_tweet_time = datetime.fromisoformat(first_tweet_info["date_time"])
                    current_time = datetime.now(jst)
                    time_diff = current_time - first_tweet_time
                    logging.info(f"最初のツイート時刻: {first_tweet_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    logging.info(f"現在時刻: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    logging.info(f"時間差: {time_diff}")
                    
                    # 最新ツイートが15分以内であれば処理を続行
                    if time_diff.total_seconds() <= 900:  # 15分以内
                        logging.info("最新ツイートが確認できました。データ取得を続行します。")
                        break
                    else:
                        logging.info(f"最新ツイートが古すぎます（{time_diff}）。再試行します...")
                        if attempt < max_wait_attempts - 1:
                            driver.refresh()
                            time.sleep(3)
                            continue
                        else:
                            logging.warning("最新ツイートの取得に失敗しました。古いデータで処理を続行します。")
                            break
            
            if attempt == max_wait_attempts - 1:
                logging.warning("最新ツイートの確認に失敗しました。処理を続行します。")
        
        time.sleep(2)  # 最終的な安定化待機
        
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
                # 時間チェック
                if time_threshold:
                    tweet_time = datetime.fromisoformat(extracted_info["date_time"])
                    if tweet_time < time_threshold:
                        logging.info(f"閾値より古いリプライが見つかりました ({tweet_time.strftime('%Y-%m-%d %H:%M:%S')})。処理を停止します。")
                        stop_processing = True
                        break

                reply_id = extracted_info.get("reply_id")
                if reply_id and reply_id not in processed_reply_ids:
                    replies_data.append(extracted_info)
                    processed_reply_ids.add(reply_id)

                    # CSVに書き込む (追記モード)
                    fieldnames = ["UserID", "Name", "date_time", "reply_id", "reply_to", "contents", "reply_num", "like_num", "is_my_thread", "lang"]
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
        while not stop_processing and scroll_count < max_scrolls:
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
                    # 時間チェック
                    if time_threshold:
                        tweet_time = datetime.fromisoformat(extracted_info["date_time"])
                        if tweet_time < time_threshold:
                            logging.info(f"閾値より古いリプライが見つかりました ({tweet_time.strftime('%Y-%m-%d %H:%M:%S')})。処理を停止します。")
                            stop_processing = True
                            break
                    
                    reply_id = extracted_info.get("reply_id")
                    if reply_id and reply_id not in processed_reply_ids:
                        replies_data.append(extracted_info)
                        processed_reply_ids.add(reply_id)

                        # CSVに書き込む (追記モード)
                        fieldnames = ["UserID", "Name", "date_time", "reply_id", "reply_to", "contents", "reply_num", "like_num", "is_my_thread", "lang"]
                        with open(output_csv_path, 'a', newline='', encoding='utf-8') as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                            if not csv_header_written:
                                writer.writeheader()
                                csv_header_written = True
                            writer.writerow(extracted_info)
                    elif reply_id:
                        logging.info(f"重複するリプライIDをスキップしました: {reply_id}")
            
            if stop_processing:
                logging.info("指定期間外のリプライに到達したため、スクロールを停止します。")
                break
            
            last_height = driver.execute_script("return document.body.scrollHeight")
            
            # 指定されたピクセル数でスクロール
            scroll_by = scroll_pixels

            # 現在のスクロール位置から指定量スクロール
            driver.execute_script(f"window.scrollBy(0, {scroll_by});")
            time.sleep(5) # スクロール後のコンテンツロードを待つ (5秒に延長)
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            
            # 新しいコンテンツがロードされなかった場合に停止
            if new_height == last_height:
                logging.info("ページがこれ以上スクロールできないため、スクロールを停止します。")
                break
        else: # whileループが正常に終了した場合
            logging.info(f"最大スクロール回数({max_scrolls}回)に達したため、スクロールを停止します。")
        
        logging.info("すべてのスクロールと抽出が完了しました。")

    except Exception as e:
        logging.error(f"リプライ取得処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        return None

    # 最終的なCSV書き込み
    if replies_data:
        logging.info(f"合計 {len(replies_data)} 件の新しいリプライを {output_csv_path} に保存しました。")
        logging.info(f"最終的に {len(processed_reply_ids)} 件のユニークなリプライが処理されました。")
        return output_csv_path
    else:
        logging.info("新しいリプライは見つかりませんでした。")
        # 新しいリプライがなくても、ファイル自体は存在している可能性があるのでパスを返す
        return output_csv_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="指定ユーザーのツイートに対するリプライを取得し、CSVリストを生成します。")
    parser.add_argument(
        "--output",
        type=str,
        help="出力CSVファイルのパス。指定しない場合はタイムスタンプ付きのファイル名が自動生成されます。"
    )
    parser.add_argument(
        "--scrolls",
        type=int,
        default=MAX_SCROLLS,
        help=f"最大スクロール回数 (デフォルト: {MAX_SCROLLS})"
    )
    parser.add_argument(
        "--pixels",
        type=int,
        default=SCROLL_PIXELS,
        help=f"1回のスクロール量（ピクセル数）(デフォルト: {SCROLL_PIXELS})"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=None,
        help="何時間前までのリプライを収集するか。指定しない場合は制限なし。"
    )
    args = parser.parse_args()

    # 出力パスが指定されていない場合、タイムスタンプ付きのパスを生成
    if not args.output:
        output_dir = "output"
        now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"extracted_tweets_{now_str}.csv"
        output_path = os.path.join(output_dir, output_file)
    else:
        output_path = args.output
    
    # このファイルが直接実行された場合のみ、driverをセットアップして終了する
    driver = None
    try:
        # 引数でheadlessモードを制御できるようにする (例: --headless)
        # ここでは簡単のため、configに合わせるか、固定値とします。
        # ユーザーの記憶に基づき、デバッグ中はFalseを維持 [[memory:2213753]]
        driver = setup_driver(headless=False) 
        if driver:
            main_process(
                driver=driver,
                output_csv_path=output_path, 
                max_scrolls=args.scrolls, 
                scroll_pixels=args.pixels, 
                hours_to_collect=args.hours
            )
    finally:
        if driver:
            driver.quit()
            logging.info("Selenium WebDriverを終了しました。") 