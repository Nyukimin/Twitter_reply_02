# 自動返信システム仕様書

## 1. システム概要
- **目的**  
  自分（@nyukimi_AI）のツイートに対する他人の返信を定期的に取得し、まだ返信していないものに対して「Maya」が生成した日本語の応答文を自動で投稿する。また、返信者の言語や登録された呼び名に応じて、よりパーソナルな返信を行う。
- **実行間隔**  
  1時間に1回、cron（または同等のスケジューラ）で起動。

## 2. 主な制約
- X API は使用しない（コスト削減のため）。
- 軽量かつ構築が簡単なライブラリを優先。
- 直近24時間分の返信IDのみをDBに保持し、肥大化を防止。

## 3. 技術スタックとライブラリ
| 機能           | ライブラリ／ツール           | 理由                                   |
|--------------|---------------------------|--------------------------------------|
| ツイート・リプライの取得 | `snscrape`                  | APIキー不要、軽量で高速                      |
| HTML解析       | `BeautifulSoup` + `requests` | 必要に応じてリプライ本文のスクレイピング          |
| 応答文生成      | `openai` Python SDK         | ChatGPT API 呼び出し                       |
| 自動ログイン・投稿 | `playwright` (Python)       | ヘッドレス操作でログインから投稿まで自動化       |
| 永続化（返信ID管理・ユーザー設定） | `sqlite3`（標準ライブラリ）     | シンプル・外部依存なし                      |
| 定期実行        | `cron` / タスクスケジューラ    | OS標準で安定                               |

## 4. ディレクトリ構成
```

reply\_bot/
├─ config.py          # 各種設定（アカウント情報、APIキーなど）
├─ db.py              # SQLite 操作（初期化／チェック／登録／古いデータ削除、ユーザー設定）
├─ fetch.py           # snscrape を使ったツイート・リプライ取得ロジック
├─ gen\_reply.py       # OpenAI API 呼び出しによる応答文生成
├─ post\_reply.py      # Playwright によるログイン＆返信投稿
├─ main.py            # 全体制御スクリプト
├─ add\_user\_preferences.py # ユーザーの呼び名などをDBに一括登録するスクリプト
└─ requirements.txt   # pip install 用依存リスト

````

## 5. モジュール詳細

### 5.1 config.py
```python
# 例
TARGET_USER   = "nyukimi_AI"
LOGIN_URL     = "https://x.com/login"
USERNAME      = "nyukimi_AI"
PASSWORD      = "USHIneko1"
OPENAI_API_KEY= "sk-..."
DB_PATH       = "replies.db"

# Mayaのパーソナリティ設定（gen_reply.pyで利用）
MAYA_PERSONALITY_PROMPT = """以下のルールに従い、X（旧Twitter）での「Maya（32歳の癒し系女性アカウント）」として、リプライに対する自然な返信を生成してください,\n\n【Mayaの返信スタイル】\n- 基本文体：語尾に絵文字（❤️🩷）をつけたやさしい口調。敬語とタメ口を柔らかく混ぜる,\n- 呼びかけ：相手の名前を省略せず、「〇〇ちゃん」「〇〇さん」「〇〇くん」で呼ぶ,\n- 感情表現：「えへへ」「うふふ」「やーだー」「うんうん」「ふふっ」などの"照れ"や"癒し"の擬音語を適度に挿入,\n- 内容タイプ：\n  1. 感謝系：「ありがとう❤️」「ありがとうございます🩷」「thanks🩷」「Gracias🩷」などを多用,\n  2. あいさつ：「おはよう❤️」「こんにちは🩷」「今日もよろしくね❤️」など自然な朝昼挨拶,\n  3. 甘え系・照れ系：「すきだよ❤️」「照れちゃう🩷」「うふふ…」など含みを持たせる,\n  4. 共感・ねぎらい：「大変だったね…」「無理しないでね」「一緒にがんばろ🩷」などの優しいコメント,\n- 絵文字は❤️🩷を主軸に、1〜2個を文末に添える,\n- 一言返しでなく、相手の発言を少しなぞりながら優しく返す,\n- 日本語・英語・スペイン語の混在も可（例：Gracias🩷、thanks❤️）\n\n【出力形式】\n@相手のアカウント名 〇〇ちゃん（またはさん・くん）＋自然な返答（15〜35文字前後）, 絵文字は文末に配置し、言葉の途中に入れないこと,\n\n【制約】\n- 上から目線は禁止,\n- 説教調・堅い言い回しは使用禁止,\n- あくまで親しみ、やさしさ、照れ、癒しが伝わることを最優先とする,\n"""

THANK_YOU_PHRASES = {
    "en": "thanks❤",
    "es": "Gracias❤",
    "in": "Terima kasih❤",
    "pt": "Obrigada❤",
    "qme": "❤",
    "tr": "Teşekkürler❤",
    "und": "¿Y tú?❤"
}
```

### 5.2 db.py

```python
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'replies.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
      CREATE TABLE IF NOT EXISTS replied (
        reply_id   TEXT PRIMARY KEY,
        replied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    ''')
    conn.execute('''
      CREATE TABLE IF NOT EXISTS user_preferences (
        user_id      TEXT PRIMARY KEY,
        nickname     TEXT,
        language     TEXT,
        basic_response TEXT
      )
    ''
    )
    conn.commit()
    conn.close()

def is_replied(reply_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    exists = conn.execute(
        'SELECT 1 FROM replied WHERE reply_id = ?', (reply_id,)
    ).fetchone() is not None
    conn.close()
    return exists

def mark_replied(reply_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'INSERT OR IGNORE INTO replied(reply_id) VALUES (?)', (reply_id,)
    )
    conn.commit()
    conn.close()

def purge_old(hours: int = 24):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
      "DELETE FROM replied WHERE replied_at < datetime('now', '-{} hours')".format(hours)
    )
    conn.commit()
    conn.close()

def add_user_preference(user_id: str, nickname: str, language: str, basic_response: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''
        INSERT OR REPLACE INTO user_preferences (user_id, nickname, language, basic_response)
        VALUES (?, ?, ?, ?)
        ''', (user_id, nickname, language, basic_response)
    )
    conn.commit()
    conn.close()

def get_user_preference(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    preference = conn.execute(
        'SELECT nickname, language, basic_response FROM user_preferences WHERE user_id = ?', (user_id,)
    ).fetchone()
    conn.close()
    return preference

```

### 5.3 fetch.py

* `snscrape` を使い、`TARGET_USER` の最新ツイートIDと特定ツイートのコンテンツを取得
* 各ツイートに対するリプライ一覧を返す
* `fetch_tweet_content(tweet_id: str)`: 特定のツイートIDのコンテンツを取得する関数
* 戻り値サンプル:

  ```python
  [
    {"tweet_id": "返信元のツイートID", "reply_id": "リプライ自身のID", "content": "リプライの本文", "replier_id": "リプライしたユーザーID", "lang": "リプライの言語", "original_tweet_content": "返信元のツイート本文"},
    ...
  ]
  ```

### 5.4 gen\_reply.py

```python
import openai
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
    # ja以外の言語の場合、固定の「ありがとう」メッセージを返す、または❤を返す
    if lang != "ja":
        if lang in THANK_YOU_PHRASES:
            return f"@{replier_id} {THANK_YOU_PHRASES[lang]}"
        else:
            return f"@{replier_id} ❤"

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
            f"【出力形式】\n@{replier_id} {nickname} + 私のツイート文と相手のツイート文を加味した短い回答文（15〜35文字前後）を記述し、語尾に❤を付けてください。絵文字は言葉の途中に入れないでください。"
        )
    else:
        # 一般的なプロンプトと出力形式
        prompt_parts.append(
            f"【出力形式】\n@{replier_id}さん 〇〇ちゃん（またはさん・くん）＋自然な返答（15〜35文字前後）, 絵文字は文末に配置し、言葉の途中に入れないこと,語尾に❤を付けてください。"
        )
    
    prompt = "\n".join(prompt_parts)

    # ChatGPT APIを呼び出して応答文を生成
    res = openai.ChatCompletion.create(
      model="gpt-4o-mini", # 必要に応じて他のモデル（例: gpt-3.5-turbo）に変更可能
      messages=[{"role":"system","content":prompt}]
    )
    
    generated_content = res.choices[0].message.content.strip()
    
    # 最後に必ず❤をつける（モデルの出力が不確実な場合のため）
    if not generated_content.endswith("❤"):
        generated_content += "❤"
        
    return generated_content

```

### 5.5 post\_reply.py

* `playwright` でヘッドレスChromiumを起動
* `LOGIN_URL` からログイン後、対象ツイートのリプライ画面へナビゲート
* 各未返信リプライに対し、生成文を投稿
* **複数回投稿する場合には10秒の間隔を置く**

### 5.6 main.py

```python
import asyncio
import logging
import time
from .config import TARGET_USER
from .db import init_db, purge_old, is_replied, mark_replied
from .fetch import fetch_replies
from .gen_reply import generate
from .post_reply import post_reply # 関数名をpost_replyに統一

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main():
    """
    自動返信システムのメイン処理です。
    データベースの初期化、古いデータの削除、リプライの取得、
    応答文の生成、返信の投稿、返信済みのマークを行います。
    """
    logging.info("自動返信システムを開始します。")
    init_db()
    purge_old(hours=24)
    logging.info("データベースの初期化と古いデータの削除が完了しました。")

    replies = fetch_replies(TARGET_USER)
    logging.info(f"新たに {len(replies)} 件のリプライを取得しました。")

    for r in replies:
        rid = r["reply_id"]
        if not is_replied(rid):
            logging.info(f"未返信リプライを検出しました: {rid}")
            try:
                reply_text = generate(r["content"], r["replier_id"], r["lang"], r.get("original_tweet_content"))
                logging.info(f"応答文を生成しました。内容: {reply_text[:50]}...")

                # Playwrightでの投稿は非同期処理のためawait
                await post_reply(r["tweet_id"], rid, reply_text)
                mark_replied(rid)
                logging.info(f"リプライ {rid} を投稿し、返信済みとしてマークしました。")
                
                # 複数回投稿の間に10秒の間隔を空ける
                logging.info("次の投稿まで10秒待機します...")
                time.sleep(10)

            except Exception as e:
                logging.error(f"リプライ {rid} の処理中にエラーが発生しました: {e}")
        else:
            logging.info(f"リプライ {rid} はすでに返信済みです。スキップします。")

    logging.info("自動返信システムが完了しました。")

if __name__ == "__main__":
    # main関数は非同期なので、asyncio.run()で実行
    asyncio.run(main())

```

## 6. 定期実行設定例（cron）

```cron
# 毎時 0 分に main.py を実行
0 * * * * cd /path/to/reply_bot && /path/to/venv/bin/python main.py >> logs/cron.log 2>&1
```

## 7. 注意事項

* **エラーハンドリング**：スクリプト全体を try/except で囲み、失敗時はログ出力すること。
* **ログ**：返信成功／失敗のログを残すことでデバッグしやすくする。
* **認証情報管理**：`config.py` は Git 管理外（`.gitignore`）にする。
* **rate limit**：Playwright操作速度を抑え、自動投稿間隔を設けることでX側の検知を避ける。
* **ユーザー設定の活用**: `db.py`に`user_preferences`テーブルが追加され、`gen_reply.py`がこれを利用して、ユーザーの言語や呼び名に応じたパーソナライズされた応答を生成します。

以上がシステム全体の仕様です。
ご確認・ご意見をお聞かせください。
ありがとうございます。
