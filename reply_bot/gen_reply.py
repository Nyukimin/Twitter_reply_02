import openai
import random
from .config import OPENAI_API_KEY, MAYA_PERSONALITY_PROMPT, THANK_YOU_PHRASES
from .db import get_user_preference

# OpenAI APIキーを設定
openai.api_key = OPENAI_API_KEY

def generate(reply_text: str, replier_id: str = None, lang: str = "en", original_tweet_content: str = None) -> str:
    """
    与えられたリプライテキストに対して、AI（Maya）が生成した応答文を返します。
    
    Args:
        reply_text (str): 返信を生成する対象のリプライ本文。
        replier_id (str): リプライを送信したユーザーのID（オプション）。
        lang (str): リプライの言語コード（デフォルトは"en"）。
        original_tweet_content (str): Mayaの元のツイート内容（オプション）。

    Returns:
        str: 生成された応答文。
    """
    # ja以外の言語の場合、固定の「ありがとう」メッセージを返す、または❤️を返す
    if lang != "ja":
        if lang in THANK_YOU_PHRASES and isinstance(THANK_YOU_PHRASES[lang], list):
            selected_phrase = random.choice(THANK_YOU_PHRASES[lang])
            return f"@{replier_id} {selected_phrase}"
        else:
            return f"@{replier_id} ❤️"

    # ユーザーの呼び名を取得（存在する場合）
    nickname = None
    if replier_id:
        preference = get_user_preference(replier_id)
        if preference:
            nickname = preference[0] # nicknameはタプルの最初の要素

    # プロンプトの構築
    prompt_parts = [
        MAYA_PERSONALITY_PROMPT,
        "以下のリプライに対して、適切で自然な日本語の返信を考えてください。",
    ]

    if original_tweet_content:
        prompt_parts.append(f"私の元のツイート内容：\"{original_tweet_content}\"")
    
    prompt_parts.append(f"相手のリプライ内容：\"{reply_text}\"")

    if nickname:
        # 近しい間柄の場合のプロンプトと出力形式
        prompt_parts.append(
            f"【出力形式】\n@{replier_id} {nickname} + 私のツイート文と相手のツイート文を加味した短い回答文（15〜35文字前後）を記述し、語尾に❤️を付けてください。絵文字は言葉の途中に入れないでください。"
        )
    else:
        # 一般的なプロンプトと出力形式
        prompt_parts.append(
            f"【出力形式】\n@{replier_id}さん 〇〇ちゃん（またはさん・くん）＋自然な返答（15〜35文字前後）, 絵文字は文末に配置し、言葉の途中に入れないこと,語尾に❤️を付けてください。"
        )
    
    prompt = "\n".join(prompt_parts)

    # ChatGPT APIを呼び出して応答文を生成
    res = openai.ChatCompletion.create(
      model="gpt-4o-mini", # 必要に応じて他のモデル（例: gpt-3.5-turbo）に変更可能
      messages=[{"role":"system","content":prompt}]
    )
    
    generated_content = res.choices[0].message.content.strip()
    
    # 最後に必ず❤️をつける（モデルの出力が不確実な場合のため）
    if not generated_content.endswith("❤️"):
        generated_content += "❤️"
        
    return generated_content

if __name__ == "__main__":
    # テスト用のリプライテキスト
    # データベースの初期化とテストデータの追加（実行前にdb.pyのinit_dbを実行しておく必要あり）
    # from .db import init_db, add_user_preference
    # init_db()
    # add_user_preference("test_user_en", "ジョン", "en", "Hello!")
    # add_user_preference("test_user_maya", "マヤちゃん", "ja", "")

    test_reply_ja_nickname = "いつも素敵なツイートありがとう！"
    test_original_tweet_ja = "今日の空はとても綺麗だったね！"
    print(f"元のリプライ (日本語、ニックネームあり): {test_reply_ja_nickname}")
    generated_response_ja_nickname = generate(test_reply_ja_nickname, "test_user_maya", "ja", test_original_tweet_ja)
    print(f"生成された返信 (日本語、ニックネームあり): {generated_response_ja_nickname}")

    test_reply_ja = "こんにちは！素晴らしいツイートでした！"
    print(f"\n元のリプライ (日本語、ニックネームなし): {test_reply_ja}")
    generated_response_ja = generate(test_reply_ja, "test_user_ja", "ja")
    print(f"生成された返信 (日本語、ニックネームなし): {generated_response_ja}")

    test_reply_en = "Hello! Great tweet!"
    print(f"\n元のリプライ (英語): {test_reply_en}")
    generated_response_en = generate(test_reply_en, "test_user_en", "en")
    print(f"生成された返信 (英語): {generated_response_en}")

    test_reply_fr = "Bonjour! C'est un bon tweet!"
    print(f"\n元のリプライ (フランス語): {test_reply_fr}")
    generated_response_fr = generate(test_reply_fr, "test_user_fr", "fr")
    print(f"生成された返信 (フランス語): {generated_response_fr}")

    test_reply_unknown_lang = "Hola!"
    print(f"\n元のリプライ (未知の言語): {test_reply_unknown_lang}")
    generated_response_unknown_lang = generate(test_reply_unknown_lang, "test_user_unknown", "xyz")
    print(f"生成された返信 (未知の言語): {generated_response_unknown_lang}") 