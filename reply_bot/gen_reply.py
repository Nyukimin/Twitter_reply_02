import google.generativeai as genai
import random
import pandas as pd
import argparse
import os
import logging
import emoji
import re
from .config import GEMINI_API_KEY, MAYA_PERSONALITY_PROMPT, THANK_YOU_PHRASES
from .db import get_user_preference

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
    # (例: ":heart:")
    if not demojized_text:
        return True # 空白や句読点のみだった場合もTrueとみなす
    
    # すべての単語が絵文字コードかチェック
    return all(re.fullmatch(r':[a-zA-Z0-9_+-]+:', word) for word in demojized_text.split())

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

    # リプライが絵文字のみの場合の処理
    if is_emoji_only(reply_text):
        logging.info(f"リプライは絵文字のみです (言語: {lang})。固定の感謝メッセージを返します。")
        # 言語に対応する感謝フレーズのリストを取得
        thank_you_list = THANK_YOU_PHRASES.get(lang, THANK_YOU_PHRASES.get("und"))
        if thank_you_list and isinstance(thank_you_list, list):
            return random.choice(thank_you_list)
        else: # 万が一、該当するキーがなかった場合やリストでない場合
            return "❤️"

    # ja以外の言語の場合、固定の「ありがとう」メッセージを返す (絵文字のみでない場合)
    if lang != "ja":
        if lang in THANK_YOU_PHRASES and isinstance(THANK_YOU_PHRASES[lang], list):
            return random.choice(THANK_YOU_PHRASES[lang])
        else:
            return "❤️"

    # ユーザーの呼び名を取得
    nickname = None
    if replier_id:
        preference = get_user_preference(replier_id.lower())
        if preference:
            nickname = preference[0]  # nicknameはタプルの最初の要素
            logging.info(f"ユーザーID '{replier_id}' のニックネーム '{nickname}' をDBから取得しました。")

    # プロンプトの構築
    prompt_parts = []
    if nickname:
        # ニックネームがある場合：Mayaのペルソナで、返信本文のみを生成させる
        prompt_parts.extend([
            MAYA_PERSONALITY_PROMPT,
            f"あなたは今から「{nickname}」さんへ返信します。",
            "以下のリプライに対して、設定されたペルソナに基づいて自然な日本語の返信を考えてください。",
        ])
        if original_tweet_content:
            prompt_parts.append(f'私の元のツイート内容："{original_tweet_content}"')
        prompt_parts.append(f'相手のリプライ内容："{reply_text}"')
        prompt_parts.append(
            "【重要事項】\n"
            "1. 返信の文章に、相手の呼びかけ（「〇〇さん」など）は絶対に入れないでください。\n"
            "2. 相手のリプライ内容を踏まえた自然な返答（15〜35文字前後）を記述してください。\n"
            "3. 語尾には必ず❤️か🩷を一つだけ付けてください。\n"
            "4. 絵文字は言葉の途中に入れないでください。"
        )
    else:
        # ニックネームがない場合：Mayaのペルソナで、でも短めに
        logging.info(f"ユーザーID '{replier_id}' のニックネームが見つからないため、Mayaのペルソナで短めの返信を生成します。")
        prompt_parts.extend([
            MAYA_PERSONALITY_PROMPT,
            "以下のリプライに対して、設定されたペルソナに基づいて自然で短い日本語の返信を考えてください。",
            f'相手のリプライ内容："{reply_text}"',
            "【重要事項】",
            "- 相手への呼びかけ（「〇〇さん」など）は絶対に含めないでください。",
            "- 返信は非常に短く、要点だけを伝えてください。（例：「ありがとう！嬉しいな❤️」「そっかそっか、お疲れ様！🩷」）",
            "- 語尾には必ず❤️か🩷を一つだけ付けてください。"
        ])

    prompt = "\n".join(prompt_parts)

    try:
        # Gemini APIを呼び出して応答文を生成
        model = genai.GenerativeModel('gemini-1.5-flash') # または 'gemini-pro'
        response = model.generate_content(prompt)
        
        generated_content = response.text.strip()
        
        # AIが生成したテキストの先頭に付いている可能性のある「@...」を削除
        generated_content = re.sub(r'^@\S+\s*', '', generated_content)

        # ニックネームがある場合、AIが生成した本文の先頭にニックネームが含まれていれば削除
        if nickname:
            # 正規表現で、先頭のニックネームとそれに続く可能性のある句読点や空白を削除
            escaped_nickname = re.escape(nickname)
            generated_content = re.sub(f'^{escaped_nickname}[、, ]*', '', generated_content).lstrip()

        # AIが語尾の絵文字を付け忘れた場合のフォールバック
        if lang == "ja" and not generated_content.endswith(("❤️", "🩷")):
            generated_content += random.choice(["❤️", "🩷"])
            
        # ニックネームがある場合は、先頭に呼びかけと改行を追加
        if nickname:
            return f"{nickname}\n{generated_content}"
        
        return generated_content
    except Exception as e:
        logging.error(f"Gemini API呼び出し中にエラーが発生しました: {e}")
        return ""


def main_process(input_csv: str, limit: int = None):
    """
    CSVファイルを読み込み、返信を生成して新しいCSVファイルに一件ずつ保存します。
    """
    logging.info(f"入力ファイル: {input_csv}")
    
    try:
        df = pd.read_csv(input_csv)
    except FileNotFoundError:
        logging.error(f"ファイルが見つかりません: {input_csv}")
        return None

    # is_my_threadがTrueの行に絞り込む
    my_thread_replies = df[df['is_my_thread'] == True].copy()
    
    if my_thread_replies.empty:
        logging.info("自分のスレッドへの返信が見つかりませんでした。処理を終了します。")
        return None

    # ユーザーの指示で件数を制限
    if limit is not None:
        logging.info(f"処理件数を {limit} 件に制限します。")
        my_thread_replies = my_thread_replies.head(limit)

    logging.info(f"自分のスレッドへの返信 {len(my_thread_replies)} 件に対して返信を生成します。")

    # 出力ファイルパスの生成
    base_name = os.path.basename(input_csv)
    # priority_replies_rechecked_ を generated_replies_ に置換
    name_part = base_name.replace('priority_replies_rechecked_', '')
    output_filename = f"generated_replies_{name_part}"
    output_path = os.path.join("output", output_filename)
    
    # ディレクトリが存在しない場合は作成
    os.makedirs("output", exist_ok=True)
    
    # 出力ファイルの準備 (ヘッダー書き込み)
    output_df_columns = list(my_thread_replies.columns) + ['generated_reply']
    pd.DataFrame(columns=output_df_columns).to_csv(output_path, index=False, encoding='utf-8-sig')

    # 一件ずつ処理して追記
    for index, row in my_thread_replies.iterrows():
        logging.info(f"返信を生成中... (対象UserID: {row['UserID']})")
        
        generated_reply = generate_reply_for_row(row)
        
        # 元の行に生成した返信を追加
        row_with_reply = row.to_dict()
        row_with_reply['generated_reply'] = generated_reply
        
        # DataFrameに変換してCSVに追記
        pd.DataFrame([row_with_reply]).to_csv(output_path, mode='a', header=False, index=False, encoding='utf-8-sig')
        logging.info(f" -> 生成された返信を {output_path} に追記しました。")
        
    logging.info(f"返信生成処理が完了しました。結果は {output_path} に保存されています。")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='AIによる返信を生成し、CSVに出力します。')
    parser.add_argument('input_csv', type=str, help='入力CSVファイルのパス (例: output/priority_replies_rechecked_YYYYMMDD_HHMMSS.csv)')
    parser.add_argument('--limit', type=int, help='処理するリプライの最大件数。')
    
    args = parser.parse_args()
    
    main_process(args.input_csv, args.limit) 