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
    REPLY_RULES_PROMPT, TARGET_USER
)
from .db import get_user_preference
from .utils import setup_driver

# --- 初期設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
genai.configure(api_key=GEMINI_API_KEY)

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
        processed_text = processed_text.replace('。 ', '。\n').replace('。　', '。\n')
        processed_text = processed_text.replace('！ ', '！\n').replace('！　', '！\n')
        processed_text = processed_text.replace('？ ', '？\n').replace('？　', '？\n')
        processed_text = processed_text.replace('… ', '…\n').replace('…　', '…\n')
        processed_text = processed_text.replace('　', '\n')
        processed_text = re.sub(r'\n+', '\n', processed_text)
    return processed_text.strip()

# --- Selenium & BeautifulSoup 解析関数 ---

def _get_tweet_text(article: BeautifulSoup) -> str:
    """記事要素からツイート本文を取得します。"""
    text_div = article.find('div', {'data-testid': 'tweetText'})
    return text_div.get_text(separator=' ', strip=True) if text_div else ""

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

def fetch_and_analyze_thread(tweet_id: str, driver: webdriver.Chrome) -> dict:
    """
    指定されたtweet_idのページにアクセスし、スレッド全体を解析して必要な情報を返します。
    ライブ情報に基づき、優先返信の判定も行います。
    """
    tweet_url = f"https://x.com/any/status/{tweet_id}"
    result = {
        "should_skip": True, "is_my_thread": False, "conversation_history": [],
        "current_reply_text": "", "current_replier_id": None, "lang": "und",
        "live_reply_count": 0, "live_like_count": 0
    }
    try:
        driver.get(tweet_url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, '//article[@data-testid="tweet"]')))
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        all_tweets = soup.find_all('article', {'data-testid': 'tweet'})

        if not all_tweets:
            logging.warning("ツイート要素が見つかりませんでした。")
            return result

        # 1. 返信対象のツイートと、それより未来のツイートがないかを確認
        target_tweet_index = -1
        for i, article in enumerate(all_tweets):
            if article.find('a', href=lambda href: href and f'/status/{tweet_id}' in href):
                target_tweet_index = i
                break
        
        if target_tweet_index == -1:
            logging.error("ページ内で返信対象のツイートが見つかりませんでした。")
            return result
        
        target_article = all_tweets[target_tweet_index]

        # 【最重要ルール】ライブ情報に基づく優先返信判定
        live_is_my_thread = (_get_author_from_article(all_tweets[0]) == TARGET_USER)
        live_reply_num = _get_live_reply_count(target_article)
        live_like_num = _get_live_like_count(target_article)
        result["is_my_thread"] = live_is_my_thread
        result["live_reply_count"] = live_reply_num
        result["live_like_count"] = live_like_num
        
        has_future_replies = len(all_tweets) > target_tweet_index + 1
        is_priority_reply = live_is_my_thread and live_reply_num == 0
        
        if has_future_replies and not is_priority_reply:
            num_future_replies = len(all_tweets) - (target_tweet_index + 1)
            logging.warning(
                f"対象ツイートの後に {num_future_replies} 件の返信があり、"
                f"かつ優先返信（ライブ情報: is_my_thread={live_is_my_thread}, reply_num={live_reply_num}）"
                "の条件を満たさないため、処理をスキップします。"
            )
            return result
        elif has_future_replies and is_priority_reply:
            logging.info(
                f"未来の返信が存在しますが、優先返信ルール（ライブ情報: is_my_thread={live_is_my_thread}, "
                f"reply_num={live_reply_num}）が適用されたため、処理を続行します。"
            )

        # 2. スキップしない場合、会話履歴と各種情報を取得
        result["should_skip"] = False
        
        # 会話履歴を積み上げる
        conversation_tweets = all_tweets[:target_tweet_index + 1]
        for article in conversation_tweets:
            author = _get_author_from_article(article) or "unknown"
            text = _get_tweet_text(article)
            result["conversation_history"].append(f"@{author}: {text}")

        # 起点と対象ツイートの情報を設定
        root_author = _get_author_from_article(all_tweets[0])
        result["is_my_thread"] = (root_author == TARGET_USER)
        
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

# --- 返信生成メインロジック ---

def generate_reply(thread_data: dict, history: list) -> str:
    """
    解析されたスレッド情報に基づき、適切な返信文を生成します。
    """
    # 状況チェック
    if thread_data["should_skip"] or not thread_data["is_my_thread"]:
        return ""

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
            "6. **【最重要創造性ルール】単調な返信はあなたの評価を著しく損ないます。絶対に避けてください。**\n"
            "   - **過去の類似表現の回避:** 以前の返信（例: 「...」）と似た言い回しや構成は使わないでください。\n"
            "   - **具体的な感情表現の義務:** 相手の言葉の**どの部分に**、あなたが**どう感じたのか**を、あなたの言葉で具体的に表現してください。 表面的な相槌ではなく、心の通った対話を意識してください。\n"
            "   - **常に新しい表現を:** あなたの豊かな感情表現の引き出しを全て使い、毎回新鮮で、相手が「また話したい」と思うような、魅力的な返信を心がけてください。これはあなたの能力を示す最大のチャンスです。"
        )
        if banned_phrases:
            avoidance_prompt += f"\n   - **【今回の絶対禁止フレーズ】**: `{', '.join(banned_phrases)}` これらの言葉は絶対に使わないでください。"
        
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
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        reply_body = format_reply(clean_generated_text(response.text), lang)
        
        final_reply = f"{nickname}\n{reply_body}" if nickname else reply_body
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

        processed_count = 0
        generated_replies_history = []

        for index, row in df.iterrows():
            tweet_id = str(row['reply_id'])
            
            # --- スレッド解析 ---
            thread_data = fetch_and_analyze_thread(tweet_id, driver)

            # 取得したライブ情報でDataFrameを更新
            df.loc[index, 'reply_num'] = thread_data['live_reply_count']
            df.loc[index, 'like_num'] = thread_data['live_like_count']
            df.loc[index, 'is_my_thread'] = thread_data['is_my_thread']

            # --- 返信生成 ---
            if thread_data and not thread_data["should_skip"]:
                generated_reply = generate_reply(thread_data, generated_replies_history)
                df.loc[index, 'generated_reply'] = generated_reply
                
                if generated_reply:
                    # 履歴にはニックネームを除いた本文のみ追加
                    reply_body = generated_reply.split('\n')[-1]
                    generated_replies_history.append(reply_body.replace('\n', ' '))
            else:
                logging.info("  -> 返信生成の対象外（自分のスレッドでない、またはスキップ対象）です。")

        # --- 出力処理 ---
        base_name = os.path.basename(input_csv)
        name_part = base_name.replace('extracted_tweets_', '')
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