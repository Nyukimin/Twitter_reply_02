# 自動返信システム仕様書

## 1. システム概要
- **目的**  
  自分（@ren_ai_coach）のツイートに対する他人の返信を定期的に取得し、まだ返信していないものに対して「Maya」が生成した日本語の応答文を自動で投稿する。
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
| 永続化（返信ID管理） | `sqlite3`（標準ライブラリ）     | シンプル・外部依存なし                      |
| 定期実行        | `cron` / タスクスケジューラ    | OS標準で安定                               |

## 4. ディレクトリ構成
```

reply\_bot/
├─ config.py          # 各種設定（アカウント情報、APIキーなど）
├─ db.py              # SQLite 操作（初期化／チェック／登録／古いデータ削除）
├─ fetch.py           # snscrape を使ったリプライ取得ロジック
├─ gen\_reply.py       # OpenAI API 呼び出しによる応答文生成
├─ post\_reply.py      # Playwright によるログイン＆返信投稿
├─ main.py            # 全体制御スクリプト
└─ requirements.txt   # pip install 用依存リスト

````

## 5. モジュール詳細

### 5.1 config.py
```python
# 例
TARGET_USER   = "ren_ai_coach"
LOGIN_URL     = "https://x.com/login"
USERNAME      = "あなたのXユーザー名"
PASSWORD      = "あなたのXパスワード"
OPENAI_API_KEY= "sk-..."
DB_PATH       = "replies.db"
````

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
```

### 5.3 fetch.py

* `snscrape` を使い、`TARGET_USER` の最新ツイートIDを取得
* 各ツイートに対するリプライ一覧を返す
* 戻り値サンプル:

  ```python
  [
    {"tweet_id": "12345", "reply_id": "67890", "content": "こんにちは！"},
    ...
  ]
  ```

### 5.4 gen\_reply.py

```python
import openai
from config import OPENAI_API_KEY

openai.api_key = OPENAI_API_KEY

def generate(reply_text: str) -> str:
    # LLMはOpenAIに限定せず、Geminiなど他のサービスも利用可能とする
    # 投稿者のパーソナリティ「Maya」をプロンプトで付与
    prompt = (
      "あなたは「Maya」というAIアシスタントです。\n"
      f"以下のリプライに対して、適切で自然な日本語の返信を考えてください：\n\"{reply_text}\""
    )
    res = openai.ChatCompletion.create(
      model="gpt-4o-mini",
      messages=[{"role":"system","content":prompt}]
    )
    return res.choices[0].message.content.strip()
```

### 5.5 post\_reply.py

* `playwright` でヘッドレスChromiumを起動
* `LOGIN_URL` からログイン後、対象ツイートのリプライ画面へナビゲート
* 各未返信リプライに対し、生成文を投稿
* **複数回投稿する場合には10秒の間隔を置く**

### 5.6 main.py

```python
from config import TARGET_USER
from db       import init_db, purge_old, is_replied, mark_replied
from fetch    import fetch_replies
from gen_reply import generate
from post_reply import post

def main():
    init_db()
    purge_old(hours=24)

    replies = fetch_replies(TARGET_USER)
    for r in replies:
        rid = r["reply_id"]
        if not is_replied(rid):
            reply_text = generate(r["content"])
            post(r["tweet_id"], rid, reply_text)
            mark_replied(rid)

if __name__ == "__main__":
    main()
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

以上がシステム全体の仕様です。
ご確認・ご意見をお聞かせください。
ありがとうございます。
