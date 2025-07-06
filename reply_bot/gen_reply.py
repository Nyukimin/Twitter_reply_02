import google.generativeai as genai
import random
import pandas as pd
import argparse
import os
import logging
import emoji
import re
from langdetect import detect, LangDetectException
from .config import GEMINI_API_KEY, MAYA_PERSONALITY_PROMPT, THANK_YOU_PHRASES
from .db import get_user_preference
from . import utils, db

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Gemini APIキーを設定
genai.configure(api_key=GEMINI_API_KEY)

def is_emoji_only(text: str) -> bool:
    """
    文字列が絵文字、空白、句読点のみで構成されているかを判定します。
    """
    if not text or not isinstance(text, str):
        return False
    # 絵文字、句読点、空白以外の文字をすべて取り除く
    text_without_symbols = re.sub(r'[^\w\s]', '', text) # まず句読点を削除
    demojized_text = emoji.demojize(text_without_symbols).strip()

    # 残った文字列が空か、コロンで囲まれた絵文字コードのみかチェック
    if not demojized_text:
        return True
    
    return all(re.fullmatch(r':[a-zA-Z0-9_+-]+:', word) for word in demojized_text.split())

def detect_language(text: str) -> str:
    """
    与えられたテキストの言語を判定します。
    """
    if not text or not text.strip():
        return "und"  # Undetermined
    try:
        # 信頼性が低い場合があるため、短いテキストでは注意が必要
        return detect(text)
    except LangDetectException:
        # logging.warning(f"言語の検出に失敗しました: {text}")
        return "und"  # Undetermined

def format_reply(text: str) -> str:
    """
    AIが生成したテキストや固定フレーズを整形し、最終的な返信文字列を作成する。
    - 不要な空白を改行に変換する
    - 絵文字を付与する
    - 前後の空白を除去する
    """
    # 1. 前後の空白を除去
    processed_text = text.strip()

    # 2. 句読点の後のスペースを改行に置換
    processed_text = processed_text.replace('。 ', '。\n').replace('。　', '。\n')
    processed_text = processed_text.replace('！ ', '！\n').replace('！　', '！\n')
    processed_text = processed_text.replace('？ ', '？\n').replace('？　', '？\n')
    processed_text = processed_text.replace('… ', '…\n').replace('…　', '…\n')

    # 3. 全角・半角スペースも改行に変換する
    processed_text = processed_text.replace('　', '\n')
    processed_text = processed_text.replace(' ', '\n')

    # 4. 複数の改行を1つにまとめる
    processed_text = re.sub(r'\n+', '\n', processed_text)

    # 5. 全体の末尾の空白・改行をきれいにする
    final_reply = processed_text.strip()

    return final_reply

def clean_generated_text(text: str) -> str:
    """
    AIが生成したテキストをルールに基づいてクリーンアップする後処理関数。
    - 許可されていない絵文字を削除する。
    - 挨拶やプレースホルダーを削除する。
    - 末尾のハートをルール通りに整形する。
    """
    # 許可する文字（日本語、英数字、基本的な記号、指定の絵文字）以外を削除
    # U+2764は❤️、U+1FA77は🩷
    allowed_chars_pattern = re.compile(
        r'[^\w\s.,!?「」『』、。ー〜…\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\u2764\u1FA77]'
    )
    cleaned_text = allowed_chars_pattern.sub('', text)

    # 冒頭の挨拶を削除
    cleaned_text = re.sub(r'^(おはようございます|おはよう|こんにちは|こんばんは)\s*', '', cleaned_text)

    # プレースホルダー「〇〇ちゃん」などを削除
    cleaned_text = re.sub(r'〇〇(ちゃん|くん|さん)', '', cleaned_text)
    
    # 前後の空白をトリム
    cleaned_text = cleaned_text.strip()

    # 末尾のハートを一旦すべて削除
    cleaned_text = cleaned_text.rstrip('❤️🩷')

    # 末尾に🩷を1つだけ追加
    cleaned_text += '🩷'

    return cleaned_text

def generate_reply_for_row(row: pd.Series, original_tweet_content: str = None) -> str:
    """
    DataFrameの行データに基づいて、AIが生成した応答文を返します。
    
    Args:
        row (pd.Series): 返信を生成する対象のリプライデータを含む行。
        original_tweet_content (str): Mayaの元のツイート内容（オプション）。

    Returns:
        str: 生成された応答文。
    """
    reply_text = row['contents']
    replier_id = row['UserID']
    lang = row.get('lang', 'und') # lang列が存在しない場合に備える

    # AIに渡す前に、リプライ本文からメンション（@ユーザー名）をすべて除去する
    cleaned_reply_text = re.sub(r'@[\w_]+', '', reply_text).strip()

    # リプライが絵文字のみの場合の処理
    if is_emoji_only(cleaned_reply_text):
        logging.info(f"リプライは絵文字のみです (言語: {lang})。固定の感謝メッセージを返します。")
        # 言語に対応する感謝フレーズのリストを取得
        thank_you_list = THANK_YOU_PHRASES.get(lang, THANK_YOU_PHRASES.get("und"))
        if thank_you_list and isinstance(thank_you_list, list):
            reply = random.choice(thank_you_list)
            return format_reply(reply)
        else: # 万が一、該当するキーがなかった場合やリストでない場合
            return "❤️"

    # ja以外の言語の場合、固定の「ありがとう」メッセージを返す (絵文字のみでない場合)
    if lang != "ja":
        if lang in THANK_YOU_PHRASES and isinstance(THANK_YOU_PHRASES[lang], list):
            reply = random.choice(THANK_YOU_PHRASES[lang])
            return format_reply(reply)
        else:
            return "❤️"

    # ユーザー情報が存在する場合のみニックネームを取得
    if replier_id:
        preference = get_user_preference(replier_id.lower())
        if preference:
            nickname = preference[0]  # nicknameはタプルの最初の要素
            logging.info(f"ユーザーID: {replier_id} のニックネーム「{nickname}」を取得しました。")
        else:
            nickname = None
            logging.info(f"ユーザーID: {replier_id} のニックネームは見つかりませんでした。")
    else:
        nickname = None
        logging.info(f"ユーザーID: {replier_id} のニックネームは見つかりませんでした。")

    original_tweet_content = row.get('original_tweet_content', '')
    cleaned_reply_text = re.sub(r'@[\w_]+', '', reply_text).strip()
    
    # --- プロンプト生成ロジックを刷新 ---
    prompt_parts = [
        MAYA_PERSONALITY_PROMPT,
        "これから、ファンからのリプライが提示されます。",
        f'ファンからのリプライ内容：「{cleaned_reply_text}」'
    ]
    if original_tweet_content:
        prompt_parts.append(f'あなたの元のツイート：「{original_tweet_content}」')

    # AIへの指示を明確化
    prompt_parts.extend([
        "【返信文の作成ルール】",
        "1. 上記のリプライ内容に対して、あなたの「返信の本文」だけを、一言またはごく短い1文で生成してください。",
        "2. **重要：相手の名前（〇〇さん）や、あなた自身の名前（Maya）、挨拶（こんにちは、など）は絶対に入れないでください。** これらはプログラムが自動で対応するため、あなたの役割は返信の「本文」作成のみです。",
        "3. 返信の語尾には、❤️か🩷のどちらか一つを必ず付けてください。文中や語尾に他の絵文字は一切入れないでください。",
        "4. 相手のリプライに性的なニュアンスが含まれている場合、困惑したり、恥ずかしがるような反応をしてください。決して喜んだり同意したりしないでください。",
        "   （適切な返答の例：「えっ、な、何言ってるの…？❤️」「もう、冗談ばっかり…🩷」「そういうのは恥ずかしいよぉ…🩷」「心臓に悪いってば…！❤️」「そんなこと言われたら、どうしたらいいか分かんないよぉ…🩷」）"
    ])

    prompt = "\n".join(prompt_parts)
    logging.debug(f"生成されたプロンプト:\n{prompt}")

    try:
        # Gemini APIを呼び出して応答文を生成
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)

        # AIが生成したテキストを後処理でクリーンアップし、その後フォーマットする
        raw_text = response.text
        cleaned_text = clean_generated_text(raw_text)
        reply_body = format_reply(cleaned_text)

        # ニックネームがある場合は、文頭に「ニックネーム＋改行」を付与する
        if nickname:
            final_reply = f"{nickname}\n{reply_body}"
            log_message = final_reply.replace('\n', '<br>')
            logging.info(f"生成された返信（ニックネーム付き）: {log_message}")
            return final_reply
        else:
            # ニックネームがない場合は、整形したテキストをそのまま返す
            log_message = reply_body.replace('\n', '<br>')
            logging.info(f"生成された返信: {log_message}")
            return reply_body

    except Exception as e:
        logging.error(f"Gemini API呼び出し中にエラーが発生しました: {e}")
        return None

    return None


def main_process(input_csv: str, limit: int = None):
    """
    CSVファイルを読み込み、返信を生成して新しいCSVファイルに保存します。
    is_my_threadがFalseの場合は、返信を生成せずにそのままコピーします。
    """
    logging.info(f"入力ファイル: {input_csv}")
    
    try:
        df = pd.read_csv(input_csv)
    except FileNotFoundError:
        logging.error(f"ファイルが見つかりません: {input_csv}")
        return None

    # is_my_thread がブール値でない可能性を考慮して変換
    if 'is_my_thread' in df.columns:
        df['is_my_thread'] = df['is_my_thread'].apply(lambda x: str(x).lower() == 'true')
    else:
        df['is_my_thread'] = False
        logging.warning("'is_my_thread' 列が見つからなかったため、すべて他人のスレッドへのリプライとして扱います。")

    # ユーザーの指示で件数を制限
    df_to_process = df.head(limit).copy() if limit is not None else df.copy()
    if limit is not None:
        logging.info(f"処理件数を {limit} 件に制限します。")

    logging.info(f"合計 {len(df_to_process)} 件のデータに対して処理を開始します。")

    # is_my_thread に基づいて返信を生成
    generated_replies = []
    for index, row in df_to_process.iterrows():
        if row['is_my_thread']:
            logging.info(f"返信を生成中... (対象UserID: {row['UserID']}, is_my_thread: True)")
            generated_replies.append(generate_reply_for_row(row))
        else:
            logging.info(f"返信生成をスキップします (対象UserID: {row['UserID']}, is_my_thread: False)")
            generated_replies.append("") # 返信を生成しない場合は空文字列

    # 生成した返信を新しい列として追加
    df_to_process['generated_reply'] = generated_replies
    
    # 出力ファイルパスの生成
    base_name = os.path.basename(input_csv)
    name_part = base_name.replace('priority_replies_rechecked_', '')
    output_filename = f"generated_replies_{name_part}"
    output_path = os.path.join("output", output_filename)
    
    # ディレクトリが存在しない場合は作成
    os.makedirs("output", exist_ok=True)

    # 結果をCSVに保存
    df_to_process.to_csv(output_path, index=False, encoding='utf-8-sig', lineterminator='\n')

    logging.info(f"返信生成処理が完了しました。結果は {output_path} に保存されています。")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='AIによる返信を生成し、CSVに出力します。')
    parser.add_argument('input_csv', type=str, help='入力CSVファイルのパス (例: output/priority_replies_rechecked_YYYYMMDD_HHMMSS.csv)')
    parser.add_argument('--limit', type=int, help='処理するリプライの最大件数。')
    
    args = parser.parse_args()
    
    main_process(args.input_csv, args.limit) 