# 自動返信システム

## 概要
このシステムは、あなたのX（旧Twitter）アカウントのツイートに対する他ユーザーからのリプライを自動的に検出し、AI（「Maya」）が生成した日本語の応答文を自動で投稿することを目的としています。

## 機能
- **X API不使用**: コストを抑えるため、公式X APIは使用しません。
- **リプライ取得**: `snscrape` を使用して、指定ユーザーのツイートに対するリプライを効率的に取得します。
- **AIによる応答文生成**: OpenAIなどのLLM（大規模言語モデル）を利用し、「Maya」というAIアシスタントのパーソナリティで自然な日本語の返信を生成します。
- **自動ログイン・投稿**: `playwright` を使用してXに自動ログインし、生成された応答文を対象のリプライに投稿します。
- **返信済み管理**: `sqlite3` を用いて、すでに返信済みのリプライIDを管理します。直近24時間分のデータのみを保持し、データベースの肥大化を防ぎます。
- **投稿間隔**: 連続して投稿する場合には、X側の検知を避けるため10秒間の間隔を空けます。
- **定期実行**: 1時間に1回、`cron`（または同等のタスクスケジューラ）によって自動実行されるように設計されています。

## 技術スタック
- Python
- `snscrape` (ツイート・リプライ取得)
- `BeautifulSoup` & `requests` (必要に応じてHTML解析)
- `openai` (LLM連携、Geminiなど他のLLMも対応可能)
- `playwright` (自動ログイン・投稿)
- `sqlite3` (データベース管理)

## ディレクトリ構成
```
reply_bot/
├─ config.py          # 各種設定（アカウント情報、APIキーなど）
├─ db.py              # SQLite 操作（初期化／チェック／登録／古いデータ削除）
├─ fetch.py           # snscrape を使ったリプライ取得ロジック
├─ gen_reply.py       # OpenAI API 呼び出しによる応答文生成
├─ post_reply.py      # Playwright によるログイン＆返信投稿
├─ main.py            # 全体制御スクリプト
└─ requirements.txt   # pip install 用依存リスト
```

## セットアップと実行

### 1. 依存ライブラリのインストール
`requirements.txt` に記載されているPythonライブラリをインストールします。

```bash
pip install -r requirements.txt
# または、各ライブラリを個別にインストール
# pip install snscrape beautifulsoup4 requests openai playwright
```

### 2. ブラウザドライバーのインストール (Playwright)
Playwrightを使用するためには、必要なブラウザドライバーをインストールする必要があります。

```bash
playwright install
```

### 3. `config.py` の設定
`reply_bot/config.py` を作成し、Xのアカウント情報やOpenAI APIキーなどを設定します。
このファイルはGit管理から除外することを推奨します（`.gitignore` に追加してください）。

```python
# reply_bot/config.py の例
TARGET_USER   = "ren_ai_coach"  # あなたのXユーザー名（@は不要）
LOGIN_URL     = "https://x.com/login"
USERNAME      = "あなたのXユーザー名" # Xのログインに使用するユーザー名またはメールアドレス
PASSWORD      = "あなたのXパスワード" # Xのログインに使用するパスワード
OPENAI_API_KEY= "sk-..."        # OpenAI APIキー
DB_PATH       = "replies.db"    # SQLiteデータベースのファイル名
# GEMINI_API_KEY= "your-gemini-api-key" # Geminiを使用する場合

# Mayaのパーソナリティ設定（例：gen_reply.pyで利用）
MAYA_PERSONALITY_PROMPT = "あなたは「Maya」というAIアシスタントです。常に丁寧語で、ユーザーに寄り添うような返信を心がけてください。"
```

### 4. 定期実行設定

システムを自動で実行するために、`cron`（Linux/macOS）またはタスクスケジューラ（Windows）に設定を追加します。

#### cron (Linux/macOS) の例:
`crontab -e` コマンドで設定ファイルを開き、以下の行を追加します。
（`/path/to/reply_bot` と `/path/to/venv/bin/python` はあなたの環境に合わせて変更してください）

```cron
# 毎時 0 分に main.py を実行
0 * * * * cd /path/to/reply_bot && /path/to/venv/bin/python main.py >> logs/cron.log 2>&1
```

#### タスクスケジューラ (Windows) の例:
Windowsのタスクスケジューラを使用して、同様の設定を行います。

## 注意事項
- エラーハンドリングとロギングは、デバッグと安定稼働のために重要です。
- `config.py` は機密情報を含むため、Git管理から除外してください。
- X側のレートリミットや自動検知を避けるため、Playwrightの操作速度や投稿間隔に注意してください。