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

def _is_tweet_a_reply(article: BeautifulSoup) -> bool:
    """
    記事要素が返信ツイートであるか（UI上に「返信先:」等の表示があるか）を判定します。
    スレッドのルート投稿（スレ主の投稿）にはこの表示がありません。
    """
    # UI上の返信先表示に使われるキーワード（多言語対応）
    reply_pattern = re.compile(r'Replying to|返信先:')
    
    # BeautifulSoupのfind機能で、article要素内にキーワードに一致するテキストが存在するかを検索
    found_text = article.find(string=reply_pattern)
    
    # テキストが見つかれば返信ツイート、見つからなければルートツイート（または単発ツイート）
    return found_text is not None

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
        root_article = all_tweets[0] # ページに表示されている一番上のツイート

        # 【新ロジック】ページ最上部のツイートが「スレの根っこ」かを判定
        # 「返信先」表示がない場合、そのツイートはスレッドの起点（スレ主の投稿）である
        is_root_of_thread = not _is_tweet_a_reply(root_article)
        root_author = _get_author_from_article(root_article)
        
        # ライブ情報に基づく「スレ主」判定
        live_is_my_thread = is_root_of_thread and (root_author == TARGET_USER)
        
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
                f"かつ優先返信（スレ主判定: {live_is_my_thread}, reply_num={live_reply_num}）"
                "の条件を満たさないため、処理をスキップします。"
            )
            return result
        elif has_future_replies and is_priority_reply:
            logging.info(
                f"未来の返信が存在しますが、優先返信ルール（スレ主判定: {live_is_my_thread}, "
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

        # is_my_threadは新しいロジックで既に設定済み
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

    # チェック5: 言語
    # AI生成の日本語返信のみを対象とする
    expected_lang = thread_data.get("lang", "und")
    if expected_lang == 'ja':
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