import logging
import pandas as pd
import argparse
import os
import time
import random
import re
import emoji
import google.generativeai as genai
from typing import List, Dict, Tuple
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .config import (
    GEMINI_API_KEY, MAYA_PERSONALITY_PROMPT, THANK_YOU_PHRASES, 
    REPLY_RULES_PROMPT, TARGET_USER, GEMINI_MODEL_NAME
)
from .db import get_user_preference
from .utils import setup_driver

# --- 初期設定 ---
import json
from datetime import datetime

# デバッグ用のロガー設定
import os
os.makedirs('log', exist_ok=True)  # logフォルダを作成

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
genai.configure(api_key=GEMINI_API_KEY)

# 複数のログファイルハンドラーを設定
# 1. スレッド解析デバッグログ
thread_debug_logger = logging.getLogger('thread_debug')
thread_debug_handler = logging.FileHandler('log/thread_debug.log', encoding='utf-8')
thread_debug_handler.setLevel(logging.DEBUG)
thread_debug_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
thread_debug_handler.setFormatter(thread_debug_formatter)
thread_debug_logger.addHandler(thread_debug_handler)
thread_debug_logger.setLevel(logging.DEBUG)

# 2. is_reply判定専用ログ
reply_judge_logger = logging.getLogger('reply_judge')
reply_judge_handler = logging.FileHandler('log/reply_judgment.log', encoding='utf-8')
reply_judge_handler.setLevel(logging.DEBUG)
reply_judge_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
reply_judge_handler.setFormatter(reply_judge_formatter)
reply_judge_logger.addHandler(reply_judge_handler)
reply_judge_logger.setLevel(logging.DEBUG)

# 3. スレッド主判定専用ログ
thread_owner_logger = logging.getLogger('thread_owner')
thread_owner_handler = logging.FileHandler('log/thread_owner_judgment.log', encoding='utf-8')
thread_owner_handler.setLevel(logging.DEBUG)
thread_owner_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
thread_owner_handler.setFormatter(thread_owner_formatter)
thread_owner_logger.addHandler(thread_owner_handler)
thread_owner_logger.setLevel(logging.DEBUG)

# 4. 総合処理ログ
process_logger = logging.getLogger('process')
process_handler = logging.FileHandler('log/main_process.log', encoding='utf-8')
process_handler.setLevel(logging.INFO)
process_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
process_handler.setFormatter(process_formatter)
process_logger.addHandler(process_handler)
process_logger.setLevel(logging.INFO)

# --- テキスト処理ヘルパー関数 (旧gen_reply.pyより) ---

def is_emoji_only(text: str) -> bool:
    if not text or not isinstance(text, str): return False
    text_without_symbols = re.sub(r'[^\w\s]', '', text)
    demojized_text = emoji.demojize(text_without_symbols).strip()
    if not demojized_text: return True
    return all(re.fullmatch(r':[a-zA-Z0-9_+-]+:', word) for word in demojized_text.split())

def clean_generated_text(text: str) -> str:
    allowed_chars_pattern = re.compile(r'[^\w\s.,!?「」『』、。ー〜…\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\u2764\u1FA77]')
    cleaned_text = allowed_chars_pattern.sub('', text)
    cleaned_text = re.sub(r'^(おはようございます|おはよう|こんにちは|こんばんは)\s*', '', cleaned_text)
    cleaned_text = re.sub(r'〇〇(ちゃん|くん|さん)', '', cleaned_text)
    cleaned_text = cleaned_text.strip().rstrip('❤️🩷') + '🩷'
    return cleaned_text

def format_reply(text: str, lang: str = 'ja') -> str:
    processed_text = text.strip()
    if lang == 'ja':
        # 基本的な改行処理のみ：句読点後のスペースと全角スペースを改行に変換
        processed_text = processed_text.replace('。 ', '。\n').replace('。　', '。\n')
        processed_text = processed_text.replace('！ ', '！\n').replace('！　', '！\n')
        processed_text = processed_text.replace('？ ', '？\n').replace('？　', '？\n')
        processed_text = processed_text.replace('… ', '…\n').replace('…　', '…\n')
        processed_text = processed_text.replace('　', '\n')
        
        # 連続する改行をまとめる
        processed_text = re.sub(r'\n+', '\n', processed_text)
    return processed_text.strip()

# --- Selenium & BeautifulSoup 解析関数 ---

def _get_tweet_text(article: BeautifulSoup) -> str:
    """記事要素からツイート本文を取得します。"""
    text_div = article.find('div', {'data-testid': 'tweetText'})
    return text_div.get_text(separator=' ', strip=True) if text_div else ""

def _is_tweet_a_reply(article: BeautifulSoup) -> bool:
    """
    記事要素が返信ツイートであるか判定します。
    複数の判定方法を組み合わせて確実に検出します。
    """
    # ツイートIDを取得してログに記録
    tweet_id = _extract_tweet_id_for_debug(article)
    author = _get_author_from_article(article)
    
    reply_judge_logger.info(f"=== 返信判定開始: ID={tweet_id}, Author={author} ===")
    
    # 方法1: UI上の返信先表示テキストを検索（多言語対応）
    reply_patterns = [
        r'Replying to',
        r'返信先:',
        r'返信先：',
        r'Replying to @',
        r'En respuesta a',  # スペイン語
        r'Répondre à',      # フランス語
        r'Antwort an',      # ドイツ語
        r'回复',            # 中国語
        r'답글',            # 韓国語
    ]
    
    reply_judge_logger.debug(f"方法1: テキストパターン検索開始")
    for pattern in reply_patterns:
        found = article.find(string=re.compile(pattern, re.IGNORECASE))
        if found:
            reply_judge_logger.info(f"返信判定成功: テキストパターン '{pattern}' で検出")
            reply_judge_logger.debug(f"  検出テキスト: '{found.strip()}'")
            return True
        else:
            reply_judge_logger.debug(f"  パターン '{pattern}': 未検出")
    
    # 方法2: data-testid属性による判定（返信ボタンを除外）
    reply_indicators = [
        '[data-testid="inReplyTo"]',  # 正確な返信先表示のみ
        '[aria-label*="Replying to"]'  # 返信先を示すaria-label
    ]
    
    reply_judge_logger.debug(f"方法2: data-testid属性検索開始")
    for selector in reply_indicators:
        elements = article.select(selector)
        if elements:
            reply_judge_logger.info(f"返信判定成功: セレクタ '{selector}' で検出")
            reply_judge_logger.debug(f"  検出要素数: {len(elements)}")
            for i, elem in enumerate(elements[:3]):  # 最初の3つを表示
                reply_judge_logger.debug(f"  要素{i+1}: {elem.name} - {elem.get('data-testid', '')} - {elem.get('aria-label', '')}")
            return True
        else:
            reply_judge_logger.debug(f"  セレクタ '{selector}': 未検出")
    
    # 方法3: URL構造による判定
    reply_judge_logger.debug(f"方法3: URL構造検索開始")
    links = article.find_all('a', href=True)
    reply_judge_logger.debug(f"  総リンク数: {len(links)}")
    
    for i, link in enumerate(links):
        href = link['href']
        if '/status/' in href and 'reply' in href.lower():
            reply_judge_logger.info(f"返信判定成功: URLパターンで検出 '{href}'")
            return True
        elif '/status/' in href:
            reply_judge_logger.debug(f"  リンク{i+1}: {href} (返信パターンなし)")
    
    # 方法4: DOM構造による判定（ツイート本文外の@メンション検出）
    reply_judge_logger.debug(f"方法4: DOM構造検索開始")
    
    # ツイート本文要素を特定
    tweet_text_div = article.find('div', {'data-testid': 'tweetText'})
    
    # ツイート本文外でのみ@メンションを検索
    parent_indicators = []
    for elem in article.find_all(['span', 'div'], string=re.compile(r'@\w+', re.IGNORECASE)):
        # ツイート本文内の@メンションは除外
        if tweet_text_div and elem in tweet_text_div.descendants:
            continue
        # "返信先" "Replying to" などの文字列と組み合わさっている@メンションのみ対象
        elem_text = elem.get_text().strip()
        parent_text = elem.parent.get_text().strip() if elem.parent else ""
        if any(keyword in parent_text.lower() for keyword in ['replying', '返信', 'respuesta', 'répondre', 'antwort', '回复', '답글']):
            parent_indicators.append(elem)
    
    reply_judge_logger.debug(f"  返信先@メンション要素数: {len(parent_indicators)}")
    
    if parent_indicators:
        reply_judge_logger.info(f"返信判定成功: 返信先@メンション({len(parent_indicators)}個)で検出")
        for i, indicator in enumerate(parent_indicators[:3]):
            reply_judge_logger.debug(f"  返信先@メンション{i+1}: '{indicator.get_text().strip()}'")
        return True
    
    # 方法5: ツイート構造の詳細分析（より厳密な返信先検出）
    reply_judge_logger.debug(f"方法5: ツイート構造詳細分析開始")
    if tweet_text_div:
        prev_siblings = tweet_text_div.find_all_previous('div')
        reply_judge_logger.debug(f"  ツイートテキスト前の要素数: {len(prev_siblings)}")
        
        for i, sibling in enumerate(prev_siblings[:5]):
            sibling_text = sibling.get_text().strip()
            # @メンションがあり、かつ返信関連のキーワードがある場合のみ
            if (sibling_text and 
                re.search(r'@\w+', sibling_text) and 
                any(keyword in sibling_text.lower() for keyword in ['replying', '返信', 'respuesta', 'répondre', 'antwort', '回复', '답글'])):
                reply_judge_logger.info(f"返信判定成功: 返信先情報で検出")
                reply_judge_logger.debug(f"  検出要素{i+1}: '{sibling_text}'")
                return True
            elif sibling_text:
                reply_judge_logger.debug(f"  要素{i+1}: '{sibling_text[:50]}...' (返信先パターンなし)")
    else:
        reply_judge_logger.debug("  ツイートテキスト要素が見つかりません")
    
    # 方法6: 新しい判定方法 - article要素のclass属性をチェック
    reply_judge_logger.debug(f"方法6: article要素のclass属性チェック")
    article_classes = article.get('class', [])
    reply_judge_logger.debug(f"  articleクラス: {article_classes}")
    
    # 方法7: data-testid="tweet"の親要素をチェック
    reply_judge_logger.debug(f"方法7: 親要素構造チェック")
    parent = article.parent
    if parent:
        parent_attrs = {k: v for k, v in parent.attrs.items() if k in ['class', 'data-testid', 'role']}
        reply_judge_logger.debug(f"  親要素属性: {parent_attrs}")
    
    reply_judge_logger.info(f"返信判定結果: 非返信ツイートと判定 (ID={tweet_id})")
    return False

def _extract_tweet_id_for_debug(article: BeautifulSoup) -> str:
    """デバッグ用のツイートID抽出（簡易版）"""
    link = article.find('a', href=lambda href: href and '/status/' in href)
    if link and 'href' in link.attrs:
        href = link['href']
        if '/status/' in href:
            return href.split('/status/')[-1].split('?')[0]
    return "unknown"

def _get_author_from_article(article: BeautifulSoup) -> str | None:
    """記事要素から投稿者のユーザーIDを取得します。"""
    user_name_div = article.find('div', {'data-testid': 'User-Name'})
    if user_name_div:
        user_link = user_name_div.find('a', {'role': 'link', 'href': lambda href: href and href.startswith('/') and '/status/' not in href})
        if user_link and 'href' in user_link.attrs:
            return user_link['href'].lstrip('/')
    return None

def _get_live_reply_count(article: BeautifulSoup) -> int:
    """記事要素からライブの返信数を取得します。見つからない場合は0を返します。"""
    try:
        # ツイートフッター内の各種統計情報を探す
        reply_div = article.find('div', {'data-testid': 'reply'})
        if reply_div:
            # "stat"というdata-testidを持つspanから数値を取得
            stat_span = reply_div.find('span', {'data-testid': 'stat'})
            if stat_span and stat_span.text.strip().isdigit():
                return int(stat_span.text.strip())
    except (ValueError, AttributeError):
        # パースエラーや要素が見つからない場合は0を返す
        pass
    return 0

def _get_live_like_count(article: BeautifulSoup) -> int:
    """記事要素からライブの「いいね」数を取得します。見つからない場合は0を返します。"""
    try:
        like_div = article.find('div', {'data-testid': 'like'})
        if like_div:
            stat_span = like_div.find('span', {'data-testid': 'stat'})
            if stat_span and stat_span.text.strip().isdigit():
                return int(stat_span.text.strip())
    except (ValueError, AttributeError):
        pass
    return 0

def _safe_scroll_to_direction(driver: webdriver.Chrome, direction: str, max_attempts: int = 3) -> bool:
    """
    安全にスクロールを実行します。
    direction: 'up' または 'down'
    """
    try:
        for attempt in range(max_attempts):
            if direction == 'up':
                driver.execute_script("window.scrollBy(0, -3000);")
            else:
                driver.execute_script("window.scrollBy(0, 3000);")
            time.sleep(1.5)  # スクロール後の待機
        return True
    except Exception as e:
        logging.warning(f"スクロール中にエラー: {e}")
        return False

def _extract_tweet_data(article: BeautifulSoup) -> dict:
    """
    記事要素から基本的なツイート情報を抽出します。
    """
    try:
        # ツイートIDの抽出（複数の方法を試行）
        tweet_id = None
        
        # 方法1: href属性から抽出
        link = article.find('a', href=lambda href: href and '/status/' in href)
        if link and 'href' in link.attrs:
            href = link['href']
            if '/status/' in href:
                tweet_id = href.split('/status/')[-1].split('?')[0]
                thread_debug_logger.debug(f"ツイートID抽出方法1成功: {tweet_id}")
        
        # 方法2: aria-labelbackupからの抽出（フォールバック）
        if not tweet_id:
            time_element = article.find('time')
            if time_element and time_element.parent:
                parent_link = time_element.parent
                if parent_link.name == 'a' and 'href' in parent_link.attrs:
                    href = parent_link['href']
                    if '/status/' in href:
                        tweet_id = href.split('/status/')[-1].split('?')[0]
                        thread_debug_logger.debug(f"ツイートID抽出方法2成功: {tweet_id}")
        
        # タイムスタンプの抽出
        timestamp = None
        time_element = article.find('time')
        if time_element and 'datetime' in time_element.attrs:
            timestamp = time_element['datetime']
        
        author = _get_author_from_article(article)
        text = _get_tweet_text(article)
        is_reply = _is_tweet_a_reply(article)
        
        # デバッグログ出力
        thread_debug_logger.debug(f"ツイートデータ抽出結果:")
        thread_debug_logger.debug(f"  ID: {tweet_id}")
        thread_debug_logger.debug(f"  作者: {author}")
        thread_debug_logger.debug(f"  テキスト: {text[:50]}{'...' if len(text) > 50 else ''}")
        thread_debug_logger.debug(f"  タイムスタンプ: {timestamp}")
        thread_debug_logger.debug(f"  返信フラグ: {is_reply}")
        
        return {
            "tweet_id": tweet_id,
            "author": author,
            "text": text,
            "timestamp": timestamp,
            "is_reply": is_reply,
            "article": article
        }
    except Exception as e:
        thread_debug_logger.error(f"ツイートデータの抽出でエラー: {e}", exc_info=True)
        return None

def _get_complete_thread(driver: webdriver.Chrome, target_tweet_id: str) -> dict:
    """
    スレッド全体を確実に取得する堅牢な実装。
    先頭・末尾・時系列順序を保証します。
    """
    try:
        thread_debug_logger.info(f"=== スレッド全体の取得開始 (target_id: {target_tweet_id}) ===")
        
        # 初期状態のページソースサイズを記録
        initial_page_size = len(driver.page_source)
        thread_debug_logger.debug(f"初期ページサイズ: {initial_page_size} 文字")
        
        # 1. 上方向にスクロールして先頭を探す
        thread_debug_logger.info("=== 先頭を探すため上方向にスクロール開始 ===")
        prev_page_size = initial_page_size
        up_scroll_count = 0
        max_up_scrolls = 10  # 最大スクロール回数を増加
        
        while up_scroll_count < max_up_scrolls:
            _safe_scroll_to_direction(driver, 'up', 1)
            time.sleep(2)
            current_page_size = len(driver.page_source)
            
            thread_debug_logger.debug(f"上スクロール{up_scroll_count + 1}回目: ページサイズ {prev_page_size} -> {current_page_size}")
            
            # ページサイズが変わらなければスクロール完了
            if current_page_size == prev_page_size:
                thread_debug_logger.info(f"上スクロール完了: {up_scroll_count + 1}回でページサイズ変化なし")
                break
            
            prev_page_size = current_page_size
            up_scroll_count += 1
        
        # 2. 下方向にスクロールして末尾を探す
        thread_debug_logger.info("=== 末尾を探すため下方向にスクロール開始 ===")
        down_scroll_count = 0
        max_down_scrolls = 10  # 最大スクロール回数を増加
        
        while down_scroll_count < max_down_scrolls:
            _safe_scroll_to_direction(driver, 'down', 1)
            time.sleep(2)
            current_page_size = len(driver.page_source)
            
            thread_debug_logger.debug(f"下スクロール{down_scroll_count + 1}回目: ページサイズ {prev_page_size} -> {current_page_size}")
            
            # ページサイズが変わらなければスクロール完了
            if current_page_size == prev_page_size:
                thread_debug_logger.info(f"下スクロール完了: {down_scroll_count + 1}回でページサイズ変化なし")
                break
            
            prev_page_size = current_page_size
            down_scroll_count += 1
        
        # 3. 現在のページ状態でツイートを取得
        thread_debug_logger.info("=== ページ解析開始 ===")
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 複数セレクタで確実にツイート要素を取得
        tweet_selectors = [
            'article[data-testid="tweet"]',
            'div[data-testid="tweet"]',
            '[role="article"]'
        ]
        
        all_articles = []
        for selector in tweet_selectors:
            articles = soup.select(selector)
            thread_debug_logger.debug(f"セレクタ '{selector}' で {len(articles)} 件の要素発見")
            if articles:
                all_articles = articles
                break
        
        if not all_articles:
            thread_debug_logger.error("ツイート要素が見つかりませんでした。")
            return None
        
        thread_debug_logger.info(f"合計 {len(all_articles)} 件のツイート要素を発見")
        
        # 4. 各ツイートのデータを抽出
        thread_debug_logger.info("=== ツイートデータ抽出開始 ===")
        tweet_data_list = []
        for i, article in enumerate(all_articles):
            thread_debug_logger.debug(f"--- 記事要素 {i+1}/{len(all_articles)} を処理中 ---")
            tweet_data = _extract_tweet_data(article)
            if tweet_data and tweet_data["tweet_id"]:
                tweet_data_list.append(tweet_data)
                thread_debug_logger.debug(f"有効なツイートデータとして追加: {tweet_data['tweet_id']}")
            else:
                thread_debug_logger.debug("無効なツイートデータのためスキップ")
        
        if not tweet_data_list:
            thread_debug_logger.error("有効なツイートデータが抽出できませんでした。")
            return None
        
        thread_debug_logger.info(f"有効なツイートデータ {len(tweet_data_list)} 件を抽出")
        
        # 5. タイムスタンプでソート（時系列順序保証）
        thread_debug_logger.info("=== 時系列ソート開始 ===")
        valid_tweets = [t for t in tweet_data_list if t["timestamp"]]
        thread_debug_logger.debug(f"タイムスタンプ有りツイート: {len(valid_tweets)} 件")
        thread_debug_logger.debug(f"タイムスタンプ無しツイート: {len(tweet_data_list) - len(valid_tweets)} 件")
        
        if valid_tweets:
            # タイムスタンプでソート前の順序をログ出力
            thread_debug_logger.debug("ソート前のタイムスタンプ順序:")
            for i, tweet in enumerate(valid_tweets):
                thread_debug_logger.debug(f"  {i}: {tweet['timestamp']} - {tweet['tweet_id']} - @{tweet['author']}")
            
            valid_tweets.sort(key=lambda x: x["timestamp"])
            timeline = valid_tweets
            
            # ソート後の順序をログ出力
            thread_debug_logger.debug("ソート後のタイムスタンプ順序:")
            for i, tweet in enumerate(timeline):
                thread_debug_logger.debug(f"  {i}: {tweet['timestamp']} - {tweet['tweet_id']} - @{tweet['author']}")
        else:
            # タイムスタンプが取得できない場合はDOM順序を維持
            thread_debug_logger.warning("タイムスタンプが取得できないため、DOM順序を使用します。")
            timeline = tweet_data_list
            
            # DOM順序をログ出力
            thread_debug_logger.debug("DOM順序:")
            for i, tweet in enumerate(timeline):
                thread_debug_logger.debug(f"  {i}: {tweet['tweet_id']} - @{tweet['author']}")
        
        # 6. 先頭と末尾の特定
        thread_debug_logger.info("=== 先頭・末尾の特定開始 ===")
        thread_head = None
        thread_tail = None
        
        if timeline:
            # 先頭: 「返信先」表示がない最初のツイート
            for i, tweet_data in enumerate(timeline):
                thread_debug_logger.debug(f"先頭候補 {i}: ID={tweet_data['tweet_id']}, is_reply={tweet_data['is_reply']}, author=@{tweet_data['author']}")
                if not tweet_data["is_reply"]:
                    thread_head = tweet_data
                    thread_debug_logger.info(f"先頭確定: {tweet_data['tweet_id']} - @{tweet_data['author']}")
                    break
            
            # フォールバック: 返信でないツイートがない場合は最初のツイート
            if not thread_head:
                thread_head = timeline[0]
                thread_debug_logger.warning(f"フォールバック先頭: {thread_head['tweet_id']} - @{thread_head['author']}")
            
            # 末尾: 時系列順で最後のツイート
            thread_tail = timeline[-1]
            thread_debug_logger.info(f"末尾確定: {thread_tail['tweet_id']} - @{thread_tail['author']}")
        
        result = {
            "head": thread_head,
            "tail": thread_tail,
            "timeline": timeline,
            "total_tweets": len(timeline)
        }
        
        # 詳細なサマリーログ
        thread_debug_logger.info("=== スレッド解析完了サマリー ===")
        thread_debug_logger.info(f"総ツイート数: {len(timeline)}")
        thread_debug_logger.info(f"先頭ツイート: {thread_head['author'] if thread_head else 'N/A'} (ID: {thread_head['tweet_id'] if thread_head else 'N/A'})")
        thread_debug_logger.info(f"末尾ツイート: {thread_tail['author'] if thread_tail else 'N/A'} (ID: {thread_tail['tweet_id'] if thread_tail else 'N/A'})")
        thread_debug_logger.info(f"上スクロール回数: {up_scroll_count}")
        thread_debug_logger.info(f"下スクロール回数: {down_scroll_count}")
        
        # 全タイムラインをJSONファイルとして出力（デバッグ用）
        debug_filename = f"log/thread_timeline_{target_tweet_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        debug_data = {
            "target_tweet_id": target_tweet_id,
            "total_tweets": len(timeline),
            "head_tweet_id": thread_head['tweet_id'] if thread_head else None,
            "tail_tweet_id": thread_tail['tweet_id'] if thread_tail else None,
            "up_scroll_count": up_scroll_count,
            "down_scroll_count": down_scroll_count,
            "timeline": [
                {
                    "tweet_id": t['tweet_id'],
                    "author": t['author'],
                    "text": t['text'][:100] + ('...' if len(t['text']) > 100 else ''),
                    "timestamp": t['timestamp'],
                    "is_reply": t['is_reply']
                }
                for t in timeline
            ]
        }
        
        with open(debug_filename, 'w', encoding='utf-8') as f:
            json.dump(debug_data, f, ensure_ascii=False, indent=2)
        thread_debug_logger.info(f"詳細なタイムラインデータを {debug_filename} に出力しました")
        
        logging.info(f"スレッド解析完了: 全{len(timeline)}ツイート、先頭={thread_head['author'] if thread_head else 'N/A'}、末尾={thread_tail['author'] if thread_tail else 'N/A'}")
        return result
        
    except Exception as e:
        thread_debug_logger.error(f"スレッド全体取得中にエラー: {e}", exc_info=True)
        logging.error(f"スレッド全体取得中にエラー: {e}", exc_info=True)
        return None

def fetch_and_analyze_thread(tweet_id: str, driver: webdriver.Chrome) -> dict:
    """
    指定されたtweet_idのページにアクセスし、スレッド全体を解析して必要な情報を返します。
    改良版: 先頭・末尾・時系列全体を確実に取得します。
    """
    tweet_url = f"https://x.com/any/status/{tweet_id}"
    result = {
        "should_skip": True, "is_my_thread": False, "conversation_history": [],
        "current_reply_text": "", "current_replier_id": None, "lang": "und",
        "live_reply_count": 0, "live_like_count": 0,
        "thread_head": None, "thread_tail": None, "full_timeline": []
    }
    
    try:
        driver.get(tweet_url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]')))
        
        # スレッド全体を取得する
        thread_data = _get_complete_thread(driver, tweet_id)
        if not thread_data:
            logging.warning("スレッドデータの取得に失敗しました。")
            return result

        # 対象ツイートの検索
        target_article = None
        target_index = -1
        for i, tweet_data in enumerate(thread_data["timeline"]):
            if tweet_data["tweet_id"] == tweet_id:
                target_article = tweet_data["article"]
                target_index = i
                break
        
        if not target_article:
            logging.error("返信対象のツイートが見つかりませんでした。")
            return result

        # スレッド情報を結果に設定
        result["thread_head"] = thread_data["head"]
        result["thread_tail"] = thread_data["tail"] 
        result["full_timeline"] = thread_data["timeline"]
        
        # 基本情報の取得
        live_reply_num = _get_live_reply_count(target_article)
        live_like_num = _get_live_like_count(target_article)
        result["live_reply_count"] = live_reply_num
        result["live_like_count"] = live_like_num
        
        # スレッド主判定（確実な先頭情報を使用）
        head_author = thread_data["head"]["author"] if thread_data["head"] else None
        live_is_my_thread = (head_author == TARGET_USER)
        result["is_my_thread"] = live_is_my_thread
        
        # スレッド主判定の詳細ログ
        thread_owner_logger.info(f"=== スレッド主判定詳細 (tweet_id: {tweet_id}) ===")
        thread_owner_logger.info(f"先頭作者: '{head_author}' (型: {type(head_author)})")
        thread_owner_logger.info(f"TARGET_USER: '{TARGET_USER}' (型: {type(TARGET_USER)})")
        thread_owner_logger.info(f"比較結果: {head_author == TARGET_USER}")
        thread_owner_logger.info(f"live_is_my_thread: {live_is_my_thread}")
        
        # 文字列比較の詳細チェック
        if head_author and TARGET_USER:
            thread_owner_logger.debug(f"head_author.strip() == TARGET_USER.strip(): {head_author.strip() == TARGET_USER.strip()}")
            thread_owner_logger.debug(f"head_author長さ: {len(head_author)}, TARGET_USER長さ: {len(TARGET_USER)}")
            thread_owner_logger.debug(f"head_author repr: {repr(head_author)}")
            thread_owner_logger.debug(f"TARGET_USER repr: {repr(TARGET_USER)}")
        
        # スレッドタイムライン詳細
        thread_owner_logger.info(f"スレッドタイムライン詳細:")
        for i, tweet_info in enumerate(thread_data["timeline"]):
            is_target_user = tweet_info["author"] == TARGET_USER
            thread_owner_logger.info(f"  {i+1}: {tweet_info['tweet_id']} - @{tweet_info['author']} (TARGET_USER: {is_target_user}, is_reply: {tweet_info['is_reply']})")
        
        logging.info(f"スレッド主判定: head_author='{head_author}', TARGET_USER='{TARGET_USER}', is_my_thread={live_is_my_thread}")
        process_logger.info(f"Tweet {tweet_id}: is_my_thread={live_is_my_thread}, head_author={head_author}")
        
        # 後続返信の存在確認（時系列での位置を確認）
        has_future_replies = target_index < len(thread_data["timeline"]) - 1
        is_priority_reply = live_is_my_thread and live_reply_num == 0
        
        if has_future_replies and not is_priority_reply:
            num_future_replies = len(thread_data["timeline"]) - (target_index + 1)
            logging.warning(
                f"対象ツイートの後に {num_future_replies} 件の返信があり、"
                f"かつ優先返信（スレ主: {live_is_my_thread}, reply_num={live_reply_num}）"
                "の条件を満たさないため、処理をスキップします。"
            )
            return result

        # 会話履歴の構築（先頭から対象ツイートまで）
        result["should_skip"] = False
        conversation_history = []
        for tweet_data in thread_data["timeline"][:target_index + 1]:
            author = tweet_data["author"]
            text = tweet_data["text"]
            conversation_history.append(f"@{author}: {text}")
        result["conversation_history"] = conversation_history
        
        # 対象ツイート情報
        result["current_reply_text"] = _get_tweet_text(target_article)
        result["current_replier_id"] = _get_author_from_article(target_article)
        
        # 言語判定
        try:
            from langdetect import detect, LangDetectException
            result["lang"] = detect(result["current_reply_text"])
        except (LangDetectException, ImportError):
            result["lang"] = "und"

        return result

    except TimeoutException:
        logging.error(f"ページのロード中にタイムアウトしました: {tweet_url}")
        return result
    except Exception as e:
        logging.error(f"スレッド解析中に予期せぬエラー: {e}", exc_info=True)
        return result

# --- 返信品質チェック関数 (新規追加) ---
def self_check_reply(
    generated_reply: str,
    thread_data: dict,
    nickname: str | None,
    banned_phrases: set
) -> Tuple[bool, str]:
    """
    生成された返信が品質基準を満たしているかセルフチェックする。
    """
    # チェック1: 空文字列でないか
    if not generated_reply or not generated_reply.strip():
        return False, "生成された返信が空です。"

    # チェック2: フォーマット（末尾の絵文字）
    if not generated_reply.strip().endswith('🩷'):
        return False, f"返信の末尾に意図した絵文字('🩷')が付いていません: {generated_reply}"

    # チェック3: ニックネーム
    if nickname and not generated_reply.startswith(nickname):
        return False, f"ニックネーム '{nickname}' が返信の冒頭に含まれていません: {generated_reply}"

    # チェック4: 禁止フレーズ
    # ニックネームを除いた本文のみをチェック対象とする
    reply_body = generated_reply.replace(f"{nickname}\n", "") if nickname else generated_reply
    for phrase in banned_phrases:
        if phrase in reply_body:
            return False, f"禁止フレーズ '{phrase}' が含まれています: {reply_body}"

    # チェック5: 言語一貫性
    expected_lang = thread_data.get("lang", "und")
    if expected_lang == 'ja':
        # 日本語の文脈で外国語が混入していないかチェック
        foreign_words = re.findall(r'\b(?:Gracias|Thanks?|Hello|Goodbye|Merci|Danke|Ciao)\b', reply_body, re.IGNORECASE)
        if foreign_words:
            return False, f"日本語の文脈で外国語 '{', '.join(foreign_words)}' が検出されました: {reply_body}"
        
        try:
            from langdetect import detect, LangDetectException
            detected_lang = detect(reply_body)
            if detected_lang != 'ja':
                return False, f"期待される言語 'ja' と異なる言語 '{detected_lang}' が検出されました: {reply_body}"
        except (LangDetectException, ImportError):
            logging.warning("言語検出ライブラリがないか、言語判定に失敗しました。言語チェックをスキップします。")


    # チェック6: AIによる自己評価
    try:
        self_check_prompt = (
            f"あなたは、以下のルールに基づいて文章を生成するAIです。\n\n"
            f"--- ルール ---\n{MAYA_PERSONALITY_PROMPT}\n{REPLY_RULES_PROMPT}\n\n"
            f"--- 生成された文章 ---\n{reply_body}\n\n"
            f"--- 質問 ---\n上記の「生成された文章」は、あなた自身が定めた上記の「ルール」をすべて遵守していますか？\n"
            f"YesかNoかのみで、理由を付けずに答えてください。"
        )
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(self_check_prompt)
        
        # 回答が 'yes' (小文字、トリム) で始まらない場合はNG
        if not response.text.strip().lower().startswith('yes'):
            return False, f"AIによる自己評価で問題を検出しました。AIの回答: {response.text}"

    except Exception as e:
        logging.error(f"AI自己評価中にエラーが発生しました: {e}")
        # 自己評価でエラーが起きた場合は、チェックをパスさせる（フェイルセーフ）
        pass

    return True, "すべてのチェックを通過しました。"


# --- 返信生成メインロジック ---

def generate_reply(thread_data: dict, history: list) -> str:
    """
    解析されたスレッド情報に基づき、適切な返信文を生成します。
    この関数が呼ばれる時点で、返信対象であることは確定している前提。
    """
    reply_text = thread_data["current_reply_text"]
    replier_id = thread_data["current_replier_id"]
    lang = thread_data["lang"]
    conversation = "\n".join(thread_data["conversation_history"])

    # メンション等を除去したクリーンなテキスト
    cleaned_reply_text = re.sub(r'@[\w_]+', '', reply_text).strip()
    cleaned_reply_text = re.sub(r'^[…,:・、。]', '', cleaned_reply_text).strip()

    # ニックネームの有無を先に取得
    preference = get_user_preference(replier_id.lower()) if replier_id else None
    nickname = preference[0] if preference else None

    # 1. 定型文での返信（ニックネームがないユーザーに限定）
    if ("おはよう" in cleaned_reply_text or "おはよー" in cleaned_reply_text) and not nickname:
        return format_reply(f"おはよう{random.choice(['❤️', '🩷'])}", lang)
    if "こんにちは" in cleaned_reply_text and not nickname:
        return format_reply(f"こんにちは{random.choice(['❤️', '🩷'])}", lang)
    if "こんばんは" in cleaned_reply_text and not nickname:
        return format_reply(f"こんばんは{random.choice(['❤️', '🩷'])}", lang)
    
    # 絵文字のみ、または短い外国語のツイートに対する応答を改善
    if is_emoji_only(cleaned_reply_text) or (lang != "ja" and len(cleaned_reply_text) <= 15):
        # qme（絵文字のみ）の場合、言語コードとして'qme'を使用する
        lang_code = 'qme' if is_emoji_only(cleaned_reply_text) else lang
        return random.choice(THANK_YOU_PHRASES.get(lang_code, ["🩷"]))

    # 2. AIによる返信
    if lang == "ja" and not nickname and len(cleaned_reply_text) <= 15:
        return random.choice(["ありがとう🩷", "嬉しいな🩷", "えへへ、照れちゃうな🩷", "ふふっ🩷", "うんうん🩷", "わーい🩷"])

    # --- プロンプト生成 ---
    logging.info(f"AIへの入力（会話履歴）:\n---\n{conversation}\n---")
    prompt_parts = [
        MAYA_PERSONALITY_PROMPT,
        "あなたは以下の会話に参加しています。最後のファンからのリプライに返信してください。",
        "--- これまでの会話 ---",
        conversation,
        "--------------------",
        REPLY_RULES_PROMPT
    ]
    if history:
        history_str = "、".join(history)
        
        # 履歴から禁止フレーズを動的に抽出
        banned_phrases = set()
        common_verbs = ["照れる", "照れちゃう", "嬉しい", "嬉しいな", "ありがとう", "頑張る", "ドキドキ", "すごい", "素敵"]
        for reply in history:
            for phrase in common_verbs:
                if phrase in reply:
                    banned_phrases.add(phrase)

        avoidance_prompt = (
            "6. **表現の多様性**: 過去の返信と同じ表現の繰り返しは避け、Mayaらしい自然な短文で返信してください。"
        )
        if banned_phrases:
            avoidance_prompt += f"\n   - 最近使った表現: `{', '.join(banned_phrases)}` は今回は使わず、別の表現で返信してください。"
        
        prompt_parts.append(avoidance_prompt)

    # ★★★ 新しいロジック: 外国語の場合は言語を指定する ★★★
    if lang != 'ja':
        language_name_map = {
            "en": "英語 (English)", "es": "スペイン語 (Spanish)", "in": "インドネシア語 (Indonesian)",
            "pt": "ポルトガル語 (Portuguese)", "tr": "トルコ語 (Turkish)", "fr": "フランス語 (French)",
            "de": "ドイツ語 (German)", "zh": "中国語 (Chinese)", "ko": "韓国語 (Korean)"
        }
        language_name = language_name_map.get(lang, lang)
        lang_prompt = (
            f"7. **【最重要言語ルール】返信は必ず**{language_name}**で記述してください。** 日本語は絶対に使用しないでください。"
        )
        prompt_parts.append(lang_prompt)

    prompt = "\n".join(prompt_parts)
    logging.debug(f"生成されたプロンプト:\n{prompt}")

    try:
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt)
        reply_body = format_reply(clean_generated_text(response.text), lang)
        
        final_reply = f"{nickname}\n{reply_body}" if nickname else reply_body

        # --- セルフチェックの実行 ---
        # banned_phrases はこのスコープで定義されている
        is_ok, check_log = self_check_reply(
            generated_reply=final_reply,
            thread_data=thread_data,
            nickname=nickname,
            banned_phrases=banned_phrases if 'banned_phrases' in locals() else set()
        )

        if not is_ok:
            logging.warning(f"返信ID {thread_data.get('tweet_id', 'N/A')} のセルフチェックで問題を発見: {check_log}")
            logging.warning(f"  -> この返信は破棄されます: {final_reply.replace(chr(10), '<br>')}")
            return "" # 問題があったため返信を空にする

        log_message = final_reply.replace('\n', '<br>')
        logging.info(f"生成された返信: {log_message}")
        return final_reply

    except Exception as e:
        logging.error(f"Gemini API呼び出し中にエラー: {e}")
        return ""

# --- パイプライン実行関数 ---

def main_process(driver: webdriver.Chrome, input_csv: str, limit: int = None) -> str | None:
    logging.info(f"'{input_csv}' の処理を開始します...")
    try:
        df = pd.read_csv(input_csv)
        if limit:
            df = df.head(limit)
            logging.info(f"処理件数を {limit} 件に制限しました。")
        df.fillna('', inplace=True)

        generated_replies_history = []
        rows_to_drop = [] # 削除対象の行インデックスを格納

        for index, row in df.iterrows():
            tweet_id = str(row['reply_id'])
            
            # --- スレッド解析 ---
            thread_data = fetch_and_analyze_thread(tweet_id, driver)
            thread_data['tweet_id'] = tweet_id # ログ出力用にIDを追加

            # 取得したライブ情報でDataFrameを更新
            df.loc[index, 'reply_num'] = thread_data['live_reply_count']
            df.loc[index, 'like_num'] = thread_data['live_like_count']
            df.loc[index, 'is_my_thread'] = thread_data['is_my_thread']

            # --- 返信生成の判断 ---
            # 自分のスレッドで、かつスキップ対象でない場合のみ返信生成を試みる
            if thread_data and not thread_data["should_skip"] and thread_data.get("is_my_thread", False):
                generated_reply = generate_reply(thread_data, generated_replies_history)
                df.loc[index, 'generated_reply'] = generated_reply
                
                if generated_reply:
                    # セルフチェックを通過し、返信が正常に生成された
                    reply_body = generated_reply.split('\n')[-1]
                    generated_replies_history.append(reply_body.replace('\n', ' '))
                else:
                    # 返信生成を試みたが、セルフチェックで失敗した
                    rows_to_drop.append(index)
            else:
                # そもそも返信対象外（自分のスレッドでない、またはスキップ対象）
                logging.info(f"  -> Tweet ID {tweet_id} は返信生成の対象外です。")
                df.loc[index, 'generated_reply'] = "" # 明示的に空にしておく

        # --- 失敗した行の処理と出力 ---
        base_name = os.path.basename(input_csv)
        name_part = base_name.replace('extracted_tweets_', '')

        if rows_to_drop:
            # 失敗した行を新しいDataFrameとして抽出し、別ファイルに保存
            failed_df = df.loc[rows_to_drop].copy()
            failed_output_filename = os.path.join("output", f"failed_selfcheck_{name_part}")
            failed_df.to_csv(failed_output_filename, index=False, encoding='utf-8-sig')
            logging.info(f"セルフチェックに失敗した {len(rows_to_drop)} 件を {failed_output_filename} に保存しました。")

            # 元のDataFrameから失敗した行を削除
            df.drop(rows_to_drop, inplace=True)
            logging.info("メインの処理対象から上記失敗件数を除外しました。")


        # --- 正常な行の出力処理 ---
        output_filename = os.path.join("output", f"processed_replies_{name_part}")
        
        df.to_csv(output_filename, index=False, encoding='utf-8-sig')
        logging.info(f"--- 全件の処理が完了し、{output_filename} に保存されました ---")
        return output_filename

    except FileNotFoundError:
        logging.error(f"入力ファイルが見つかりません: {input_csv}")
        return None
    except Exception as e:
        logging.error(f"メインプロセス中に予期せぬエラー: {e}", exc_info=True)
        return None

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="スレッドを解析し、文脈に応じた返信を生成します。")
    parser.add_argument("input_csv", help="入力CSVファイルのパス (extracted_tweets_...csv)")
    parser.add_argument("--limit", type=int, help="処理するリプライの最大数")
    args = parser.parse_args()

    driver = None
    try:
        driver = setup_driver(headless=False)
        if driver:
            main_process(driver, args.input_csv, args.limit)
    finally:
        if driver:
            driver.quit()
            logging.info("Selenium WebDriverを終了しました。") 