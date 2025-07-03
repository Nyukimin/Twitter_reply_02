import openai
from .config import OPENAI_API_KEY, MAYA_PERSONALITY_PROMPT

# OpenAI APIキーを設定
openai.api_key = OPENAI_API_KEY

def generate(reply_text: str) -> str:
    """
    与えられたリプライテキストに対して、AI（Maya）が生成した応答文を返します。
    
    Args:
        reply_text (str): 返信を生成する対象のリプライ本文。

    Returns:
        str: 生成された応答文。
    """
    # プロンプトにMayaのパーソナリティを付与
    prompt = (
      f"{MAYA_PERSONALITY_PROMPT}\n"
      f"以下のリプライに対して、適切で自然な日本語の返信を考えてください：\n\"{reply_text}\""
    )
    
    # ChatGPT APIを呼び出して応答文を生成
    res = openai.ChatCompletion.create(
      model="gpt-4o-mini", # 必要に応じて他のモデル（例: gpt-3.5-turbo）に変更可能
      messages=[{"role":"system","content":prompt}]
    )
    
    return res.choices[0].message.content.strip()

if __name__ == "__main__":
    # テスト用のリプライテキスト
    test_reply = "こんにちは！素晴らしいツイートでした！"
    print(f"元のリプライ: {test_reply}")
    generated_response = generate(test_reply)
    print(f"生成された返信: {generated_response}")

    test_reply_2 = "このテーマについてもっと詳しく知りたいです！"
    print(f"\n元のリプライ: {test_reply_2}")
    generated_response_2 = generate(test_reply_2)
    print(f"生成された返信: {generated_response_2}") 