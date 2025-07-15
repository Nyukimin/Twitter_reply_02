"""
スレッド洗い出し処理の改善版
完全なスレッド取得を保証する堅牢な実装
"""

import time
import logging
from bs4 import BeautifulSoup
from selenium import webdriver
from typing import List, Dict, Set

def _robust_scroll_to_extremes(driver: webdriver.Chrome, direction: str, target_tweet_id: str) -> Dict:
    """
    より堅牢なスクロール処理で確実に先頭・末尾まで到達
    """
    scroll_data = {
        "scroll_count": 0,
        "unique_tweets_found": set(),
        "stable_iterations": 0,
        "max_stable": 3  # 連続で変化がない回数
    }
    
    while scroll_data["scroll_count"] < 15:  # 最大15回
        # スクロール実行
        if direction == 'up':
            driver.execute_script("window.scrollTo(0, 0);")  # トップまで一気に
            time.sleep(1)
            driver.execute_script("window.scrollBy(0, -5000);")
        else:
            driver.execute_script("window.scrollBy(0, 5000);")
        
        time.sleep(3)  # 遅延読み込み待機
        
        # 現在のツイートIDセットを取得
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        current_tweets = set()
        
        for selector in ['article[data-testid="tweet"]', '[role="article"]']:
            articles = soup.select(selector)
            for article in articles:
                tweet_id = _extract_tweet_id_robust(article)
                if tweet_id:
                    current_tweets.add(tweet_id)
        
        # 新しいツイートが見つかったかチェック
        prev_count = len(scroll_data["unique_tweets_found"])
        scroll_data["unique_tweets_found"].update(current_tweets)
        new_count = len(scroll_data["unique_tweets_found"])
        
        if new_count == prev_count:
            scroll_data["stable_iterations"] += 1
        else:
            scroll_data["stable_iterations"] = 0
        
        scroll_data["scroll_count"] += 1
        
        # 安定状態の判定
        if scroll_data["stable_iterations"] >= scroll_data["max_stable"]:
            break
    
    return scroll_data

def _extract_tweet_id_robust(article: BeautifulSoup) -> str:
    """
    より確実なツイートID抽出
    """
    # 方法1: 複数のhref属性パターンを試行
    href_patterns = [
        lambda href: href and '/status/' in href,
        lambda href: href and href.startswith('/') and len(href.split('/')) >= 3
    ]
    
    for pattern in href_patterns:
        links = article.find_all('a', href=pattern)
        for link in links:
            href = link.get('href', '')
            if '/status/' in href:
                tweet_id = href.split('/status/')[-1].split('?')[0].split('/')[0]
                if tweet_id.isdigit() and len(tweet_id) > 10:
                    return tweet_id
    
    # 方法2: time要素の親リンクから抽出
    time_elements = article.find_all('time')
    for time_el in time_elements:
        parent = time_el.parent
        while parent and parent.name != 'article':
            if parent.name == 'a' and 'href' in parent.attrs:
                href = parent['href']
                if '/status/' in href:
                    tweet_id = href.split('/status/')[-1].split('?')[0].split('/')[0]
                    if tweet_id.isdigit() and len(tweet_id) > 10:
                        return tweet_id
            parent = parent.parent
    
    return None

def _get_complete_thread_improved(driver: webdriver.Chrome, target_tweet_id: str) -> dict:
    """
    改善されたスレッド全体取得処理
    """
    try:
        logging.info(f"=== 改善版スレッド取得開始: {target_tweet_id} ===")
        
        # 1. 上方向の徹底的なスクロール
        up_data = _robust_scroll_to_extremes(driver, 'up', target_tweet_id)
        logging.info(f"上スクロール完了: {up_data['scroll_count']}回, ユニークツイート{len(up_data['unique_tweets_found'])}件")
        
        # 2. 下方向の徹底的なスクロール  
        down_data = _robust_scroll_to_extremes(driver, 'down', target_tweet_id)
        logging.info(f"下スクロール完了: {down_data['scroll_count']}回, ユニークツイート{len(down_data['unique_tweets_found'])}件")
        
        # 3. 全ツイートIDの統合
        all_unique_ids = up_data['unique_tweets_found'] | down_data['unique_tweets_found']
        logging.info(f"総発見ツイートID数: {len(all_unique_ids)}")
        
        # 4. 最終的なページ解析
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 全セレクタで重複排除しながら取得
        all_articles = []
        found_ids = set()
        
        for selector in ['article[data-testid="tweet"]', 'div[data-testid="tweet"]', '[role="article"]']:
            articles = soup.select(selector)
            for article in articles:
                tweet_id = _extract_tweet_id_robust(article)
                if tweet_id and tweet_id not in found_ids:
                    all_articles.append(article)
                    found_ids.add(tweet_id)
        
        logging.info(f"最終解析で {len(all_articles)} 件の記事要素を取得")
        
        # 5. データ抽出と構造化
        timeline = []
        for article in all_articles:
            tweet_data = _extract_tweet_data_improved(article)
            if tweet_data and tweet_data["tweet_id"]:
                timeline.append(tweet_data)
        
        # 6. 時系列ソート（改善版）
        timeline = _sort_timeline_improved(timeline)
        
        # 7. 先頭・末尾特定（改善版）
        thread_head = _find_thread_head_improved(timeline)
        thread_tail = timeline[-1] if timeline else None
        
        result = {
            "head": thread_head,
            "tail": thread_tail, 
            "timeline": timeline,
            "total_tweets": len(timeline),
            "debug_info": {
                "up_scrolls": up_data['scroll_count'],
                "down_scrolls": down_data['scroll_count'],
                "unique_ids_found": len(all_unique_ids),
                "final_articles": len(all_articles)
            }
        }
        
        logging.info(f"改善版スレッド解析完了: {len(timeline)}ツイート")
        return result
        
    except Exception as e:
        logging.error(f"改善版スレッド取得エラー: {e}", exc_info=True)
        return None

def _extract_tweet_data_improved(article: BeautifulSoup) -> dict:
    """改善されたツイートデータ抽出"""
    try:
        # ツイートIDの抽出（堅牢性向上）
        tweet_id = _extract_tweet_id_robust(article)
        if not tweet_id:
            return None
        
        # 作者の抽出（複数方法を試行）
        author = _get_author_robust(article)
        
        # ツイート本文の抽出（複数セレクタを試行）
        text = _get_tweet_text_robust(article)
        
        # タイムスタンプの抽出（改善版）
        timestamp = _get_timestamp_robust(article)
        
        # 返信判定（改善された関数を使用）
        from .reply_processor import _is_tweet_a_reply
        is_reply = _is_tweet_a_reply(article)
        
        # ライブ数値の抽出
        reply_count = _get_live_reply_count_robust(article)
        like_count = _get_live_like_count_robust(article)
        
        return {
            "tweet_id": tweet_id,
            "author": author,
            "text": text,
            "timestamp": timestamp,
            "is_reply": is_reply,
            "reply_count": reply_count,
            "like_count": like_count,
            "article": article
        }
    except Exception as e:
        logging.error(f"改善版ツイートデータ抽出エラー: {e}", exc_info=True)
        return None

def _get_author_robust(article: BeautifulSoup) -> str:
    """堅牢な作者情報抽出"""
    # 方法1: 従来のUser-Name要素
    user_name_div = article.find('div', {'data-testid': 'User-Name'})
    if user_name_div:
        user_link = user_name_div.find('a', {'role': 'link'})
        if user_link and 'href' in user_link.attrs:
            href = user_link['href']
            if href.startswith('/') and '/status/' not in href:
                return href.lstrip('/')
    
    # 方法2: プロフィールリンクの検索
    profile_links = article.find_all('a', href=lambda x: x and x.startswith('/') and '/status/' not in x and x.count('/') == 1)
    for link in profile_links:
        username = link['href'].lstrip('/')
        if username and len(username) > 1 and len(username) < 50:  # 妥当な長さ
            return username
    
    # 方法3: span要素内のユーザー名検索
    user_spans = article.find_all('span', string=lambda text: text and text.startswith('@'))
    for span in user_spans:
        username = span.get_text().lstrip('@')
        if username and len(username) > 1:
            return username
    
    return None

def _get_tweet_text_robust(article: BeautifulSoup) -> str:
    """堅牢なツイート本文抽出"""
    # 複数のセレクタを試行
    text_selectors = [
        {'data-testid': 'tweetText'},
        {'data-testid': 'tweetContent'},
        {'data-testid': 'text'},
        {'role': 'text'}
    ]
    
    for selector in text_selectors:
        text_div = article.find('div', selector)
        if text_div:
            return text_div.get_text(separator=' ', strip=True)
    
    # フォールバック: lang属性のある要素からテキスト抽出
    lang_elements = article.find_all(['div', 'span'], attrs={'lang': True})
    for elem in lang_elements:
        text = elem.get_text(strip=True)
        if text and len(text) > 5:  # 短すぎるテキストは除外
            return text
    
    return ""

def _get_timestamp_robust(article: BeautifulSoup) -> str:
    """堅牢なタイムスタンプ抽出"""
    # 方法1: time要素のdatetime属性
    time_element = article.find('time')
    if time_element and 'datetime' in time_element.attrs:
        return time_element['datetime']
    
    # 方法2: data-time属性の検索
    time_attrs = ['data-time', 'data-timestamp', 'data-created-at']
    for attr in time_attrs:
        elem = article.find(attrs={attr: True})
        if elem:
            return elem[attr]
    
    # 方法3: ISO日付形式の文字列検索
    import re
    all_text = article.get_text()
    iso_pattern = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}'
    match = re.search(iso_pattern, all_text)
    if match:
        return match.group()
    
    return None

def _get_live_reply_count_robust(article: BeautifulSoup) -> int:
    """堅牢な返信数抽出"""
    try:
        # 方法1: 従来のreply要素
        reply_div = article.find('div', {'data-testid': 'reply'})
        if reply_div:
            stat_span = reply_div.find('span', {'data-testid': 'stat'})
            if stat_span and stat_span.text.strip().isdigit():
                return int(stat_span.text.strip())
        
        # 方法2: aria-labelから数値抽出
        reply_buttons = article.find_all(['button', 'div'], attrs={'aria-label': lambda x: x and '返信' in x})
        for button in reply_buttons:
            aria_label = button.get('aria-label', '')
            numbers = re.findall(r'\d+', aria_label)
            if numbers:
                return int(numbers[0])
        
        # 方法3: 返信アイコン周辺のテキスト
        reply_pattern = r'返信.*?(\d+)|(\d+).*?返信|reply.*?(\d+)|(\d+).*?reply'
        match = re.search(reply_pattern, article.get_text(), re.IGNORECASE)
        if match:
            for group in match.groups():
                if group:
                    return int(group)
    except (ValueError, AttributeError):
        pass
    return 0

def _get_live_like_count_robust(article: BeautifulSoup) -> int:
    """堅牢ないいね数抽出"""
    try:
        # 方法1: 従来のlike要素
        like_div = article.find('div', {'data-testid': 'like'})
        if like_div:
            stat_span = like_div.find('span', {'data-testid': 'stat'})
            if stat_span and stat_span.text.strip().isdigit():
                return int(stat_span.text.strip())
        
        # 方法2: aria-labelから数値抽出
        like_buttons = article.find_all(['button', 'div'], attrs={'aria-label': lambda x: x and ('いいね' in x or 'like' in x.lower())})
        for button in like_buttons:
            aria_label = button.get('aria-label', '')
            numbers = re.findall(r'\d+', aria_label)
            if numbers:
                return int(numbers[0])
        
        # 方法3: ハートアイコン周辺のテキスト
        like_pattern = r'いいね.*?(\d+)|(\d+).*?いいね|like.*?(\d+)|(\d+).*?like'
        match = re.search(like_pattern, article.get_text(), re.IGNORECASE)
        if match:
            for group in match.groups():
                if group:
                    return int(group)
    except (ValueError, AttributeError):
        pass
    return 0

def _sort_timeline_improved(timeline: List[dict]) -> List[dict]:
    """改善されたタイムラインソート"""
    if not timeline:
        return timeline
    
    # タイムスタンプとDOM順序を組み合わせた安定ソート
    # 時系列情報が不完全な場合の補完ロジック
    
    # 1. タイムスタンプが有効なツイートと無効なツイートを分離
    valid_timestamp_tweets = []
    invalid_timestamp_tweets = []
    
    for i, tweet in enumerate(timeline):
        tweet['original_order'] = i  # 元の順序を保存
        if tweet.get('timestamp'):
            try:
                # タイムスタンプの妥当性チェック
                from datetime import datetime
                if isinstance(tweet['timestamp'], str):
                    # ISO形式の文字列をdatetimeに変換してみる
                    datetime.fromisoformat(tweet['timestamp'].replace('Z', '+00:00'))
                valid_timestamp_tweets.append(tweet)
            except (ValueError, TypeError):
                invalid_timestamp_tweets.append(tweet)
        else:
            invalid_timestamp_tweets.append(tweet)
    
    logging.info(f"タイムラインソート: 有効タイムスタンプ{len(valid_timestamp_tweets)}件, 無効{len(invalid_timestamp_tweets)}件")
    
    # 2. 有効なタイムスタンプのツイートを時系列順にソート
    if valid_timestamp_tweets:
        valid_timestamp_tweets.sort(key=lambda x: x['timestamp'])
    
    # 3. 無効なタイムスタンプのツイートは元の順序を維持
    invalid_timestamp_tweets.sort(key=lambda x: x['original_order'])
    
    # 4. 時系列的に妥当な位置に無効ツイートを挿入
    # ツイートIDの数値的順序を参考にする（TwitterのIDは時系列順）
    result = []
    
    if valid_timestamp_tweets and invalid_timestamp_tweets:
        # 有効ツイートの間に無効ツイートを適切に配置
        for tweet in valid_timestamp_tweets + invalid_timestamp_tweets:
            # ツイートID（雪花アルゴリズム）による順序付けを試行
            if tweet.get('tweet_id') and tweet['tweet_id'].isdigit():
                tweet['id_numeric'] = int(tweet['tweet_id'])
            else:
                tweet['id_numeric'] = tweet['original_order']
        
        # IDの数値順でソート（これが最も確実な時系列順）
        all_tweets = valid_timestamp_tweets + invalid_timestamp_tweets
        all_tweets.sort(key=lambda x: x.get('id_numeric', x['original_order']))
        result = all_tweets
    elif valid_timestamp_tweets:
        result = valid_timestamp_tweets
    else:
        result = invalid_timestamp_tweets
    
    # 5. 元の順序情報を削除
    for tweet in result:
        tweet.pop('original_order', None)
        tweet.pop('id_numeric', None)
    
    logging.info(f"ソート完了: {len(result)}件のツイートを時系列順に整列")
    return result

def _find_thread_head_improved(timeline: List[dict]) -> dict:
    """改善されたスレッド先頭特定"""
    if not timeline:
        return None
    
    # 複数の判定基準を組み合わせた先頭特定
    # is_reply以外の指標も考慮
    
    logging.info(f"スレッド先頭特定開始: {len(timeline)}件のツイートを分析")
    
    # 1. 基本的な返信でないツイートを最優先で検索
    non_reply_tweets = [tweet for tweet in timeline if not tweet.get('is_reply', False)]
    
    if non_reply_tweets:
        # 返信でないツイートの中で最も古い（ID最小）ものを選択
        head_candidate = min(non_reply_tweets, key=lambda x: int(x.get('tweet_id', '0')) if x.get('tweet_id', '').isdigit() else 0)
        logging.info(f"先頭特定: 非返信ツイート '{head_candidate.get('tweet_id')}' を選択")
        return head_candidate
    
    # 2. 全てが返信の場合: 多段階判定
    logging.warning("全ツイートが返信と判定されています。多段階判定を実行します。")
    
    # 2-1. ツイートIDが最小（最古）のものを候補とする
    oldest_by_id = min(timeline, key=lambda x: int(x.get('tweet_id', '0')) if x.get('tweet_id', '').isdigit() else float('inf'))
    
    # 2-2. タイムスタンプが最古のものを候補とする
    oldest_by_time = None
    if any(tweet.get('timestamp') for tweet in timeline):
        tweets_with_time = [tweet for tweet in timeline if tweet.get('timestamp')]
        if tweets_with_time:
            oldest_by_time = min(tweets_with_time, key=lambda x: x['timestamp'])
    
    # 2-3. @メンション数が最少のものを候補とする（返信らしさが低い）
    import re
    for tweet in timeline:
        tweet_text = tweet.get('text', '')
        mentions = re.findall(r'@\w+', tweet_text)
        tweet['mention_count'] = len(mentions)
    
    least_mentions = min(timeline, key=lambda x: x.get('mention_count', 0))
    
    # 2-4. ツイート本文が最も長いもの（独立したコンテンツの可能性）
    longest_text = max(timeline, key=lambda x: len(x.get('text', '')))
    
    # 2-5. 複合スコアによる判定
    candidates = {
        'oldest_id': oldest_by_id,
        'oldest_time': oldest_by_time,
        'least_mentions': least_mentions,
        'longest_text': longest_text
    }
    
    # 各候補にスコアを付与
    candidate_scores = {}
    for name, candidate in candidates.items():
        if candidate:
            score = 0
            tweet_id = candidate.get('tweet_id')
            
            # ID順序スコア（古いほど高スコア）
            if tweet_id and tweet_id.isdigit():
                id_rank = sum(1 for t in timeline if t.get('tweet_id', '').isdigit() and int(t['tweet_id']) > int(tweet_id))
                score += id_rank * 10
            
            # @メンション数スコア（少ないほど高スコア）
            mention_count = candidate.get('mention_count', 0)
            score += max(0, (10 - mention_count)) * 5
            
            # テキスト長スコア（長いほど高スコア、ただし上限あり）
            text_length = len(candidate.get('text', ''))
            score += min(text_length // 10, 20)
            
            # タイムスタンプ順序スコア
            if candidate.get('timestamp'):
                time_rank = sum(1 for t in timeline if t.get('timestamp') and t['timestamp'] > candidate['timestamp'])
                score += time_rank * 8
            
            candidate_scores[name] = (candidate, score)
            logging.debug(f"候補 '{name}' - ID:{tweet_id}, Score:{score}, Mentions:{mention_count}, TextLen:{text_length}")
    
    # 最高スコアの候補を選択
    if candidate_scores:
        best_candidate_name, (best_candidate, best_score) = max(candidate_scores.items(), key=lambda x: x[1][1])
        logging.info(f"先頭特定: 複合判定で候補 '{best_candidate_name}' (スコア:{best_score}) を選択")
        
        # mention_count は一時的な属性なので削除
        for tweet in timeline:
            tweet.pop('mention_count', None)
        
        return best_candidate
    
    # 3. フォールバック: 最初のツイート
    logging.warning("先頭特定に失敗。最初のツイートを選択します。")
    return timeline[0] if timeline else None