import openai
import random
import pandas as pd
import argparse
import os
import logging
from .config import OPENAI_API_KEY, MAYA_PERSONALITY_PROMPT, THANK_YOU_PHRASES
# from .db import get_user_preference # DB連携は一旦コメントアウト

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# OpenAI APIキーを設定
openai.api_key = OPENAI_API_KEY

def generate_reply_for_row(row: pd.Series, original_tweet_content: str = None) -> str:
    """
    DataFrameの行データに基づいて、AIが生成した応答文を返します。
    
    Args:
        row (pd.Series): 返信を生成する対象のリプライデータを含む行。
        original_tweet_content (str): Mayaの元のツイート内容（オプション）。

    Returns:
        str: 生成された応答文。
    """
    reply_text = row['text']
    replier_id = row['user_id']
    # lang = row['lang'] # lang列がCSVに存在する場合
    lang = "ja" # 現状は日本語に固定

    # ja以外の言語の場合、固定の「ありがとう」メッセージを返す、または❤️を返す
    if lang != "ja":
        if lang in THANK_YOU_PHRASES and isinstance(THANK_YOU_PHRASES[lang], list):
            selected_phrase = random.choice(THANK_YOU_PHRASES[lang])
            return f"@{replier_id} {selected_phrase}"
        else:
            return f"@{replier_id} ❤️"

    # ユーザーの呼び名を取得（存在する場合）- DB連携は一旦停止
    nickname = None
    # if replier_id:
    #     preference = get_user_preference(replier_id)
    #     if preference:
    #         nickname = preference[0] # nicknameはタプルの最初の要素

    # プロンプトの構築
    prompt_parts = [
        MAYA_PERSONALITY_PROMPT,
        "以下のリプライに対して、適切で自然な日本語の返信を考えてください。",
    ]

    if original_tweet_content:
        prompt_parts.append(f"私の元のツイート内容：\"{original_tweet_content}\"")
    
    prompt_parts.append(f"相手のリプライ内容：\"{reply_text}\"")

    # ニックネームの有無で分岐していたが、一旦シンプルな形式に統一
    prompt_parts.append(
        f"【出力形式】\n@{replier_id}さん + 相手のリプライ内容を踏まえた自然な返答（15〜35文字前後）を記述し、語尾に❤️か🩷を付けてください。絵文字は言葉の途中に入れないでください。"
    )
    
    prompt = "\n".join(prompt_parts)

    try:
        # ChatGPT APIを呼び出して応答文を生成
        res = openai.ChatCompletion.create(
          model="gpt-4o-mini", # 必要に応じて他のモデル（例: gpt-3.5-turbo）に変更可能
          messages=[{"role":"system","content":prompt}]
        )
        
        generated_content = res.choices[0].message.content.strip()
        
        # 最後に必ず❤️か🩷をつける（モデルの出力が不確実な場合のため）
        if not generated_content.endswith(("❤️", "🩷")):
            generated_content += random.choice(["❤️", "🩷"])
            
        return generated_content
    except Exception as e:
        logging.error(f"OpenAI API呼び出し中にエラーが発生しました: {e}")
        return ""


def main_process(input_csv: str):
    """
    CSVファイルを読み込み、返信を生成して新しいCSVファイルに保存します。
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
        # 対象がなくても、後続処理のために空のCSVを出力するか、Noneを返すか
        # ここではNoneを返して、main.py側で処理を中断させる
        return None

    logging.info(f"自分のスreadへの返信 {len(my_thread_replies)} 件に対して返信を生成します。")

    # 返信を生成して新しい列に追加
    # tqdmなどを使うと進捗がわかりやすいが、一旦シンプルに実装
    my_thread_replies['generated_reply'] = my_thread_replies.apply(generate_reply_for_row, axis=1)

    # 出力ファイルパスの生成
    base_name = os.path.basename(input_csv)
    # priority_replies_rechecked_ を generated_replies_ に置換
    name_part = base_name.replace('priority_replies_rechecked_', '')
    output_filename = f"generated_replies_{name_part}"
    output_path = os.path.join("output", output_filename)
    
    # ディレクトリが存在しない場合は作成
    os.makedirs("output", exist_ok=True)
    
    # 結果をCSVに出力
    my_thread_replies.to_csv(output_path, index=False, encoding='utf-8-sig')
    logging.info(f"返信生成結果を {output_path} に保存しました。")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='AIによる返信を生成し、CSVに出力します。')
    parser.add_argument('input_csv', type=str, help='入力CSVファイルのパス (例: output/priority_replies_rechecked_YYYYMMDD_HHMMSS.csv)')
    
    args = parser.parse_args()
    
    main_process(args.input_csv) 