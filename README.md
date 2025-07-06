# 自動返信システム

## 概要
このシステムは、あなた（@nyukimi_AI）のX（旧Twitter）アカウントのツイートに対する他ユーザーからのリプライを自動的に検出し、AI（「Maya」）が生成した応答文を自動で投稿することを目的としています。**リプライがスレッド形式（会話の途中）である場合、その起点となる元ツイートが自分（Maya）の投稿であるかどうかをたどって確認し、その結果（`is_my_thread` フラグ）に基づいて、AIによる返信を生成・投稿するかどうかを制御します。**また、返信者の言語やデータベースに登録された呼び名に応じて、よりパーソナルかつ適切な返信を行います。

## 機能
- **X API不使用**: コストを抑えるため、公式X APIは使用しません。
- **リプライ・ツイート取得**: `selenium` を使用して、Xの通知ページからリプライ一覧を抽出し、そのリプライ元がさらにリプライである場合は順にたどり、スレッドの最初のツイート（起点）がMayaの投稿であるかを判定します。
- **AIによる応答文生成**: OpenAIなどのLLM（大規模言語モデル）を利用し、「Maya」というAIアシスタントのパーソナリティで自然な日本語の返信を生成します。`is_my_thread` フラグが `True`（自分のスレッドへの返信）の場合のみAIによる返信を生成し、`False` の場合は返信を生成しません。
- **自動ログイン・投稿**: `selenium` を使用してXに自動ログインし、生成された応答文を対象のリプライに投稿します。投稿は `is_my_thread` が `True` の場合に限定されます。ただし、「いいね」は `is_my_thread` の状態に関わらず、相手のいいね数が0の場合に行われます。Cookie (`twitter_cookies_01.pkl`) を使用してログイン状態を維持します。
- **返信済み管理とユーザー設定**: `sqlite3` を用いて、すでに返信済みのリプライIDと、ユーザーごとの呼び名、言語、**およびスレッド起点情報（`is_my_thread`）**などの設定情報を管理します。直近24時間分のリプライデータのみを保持し、データベースの肥大化を防ぎます。
- **投稿間隔**: 連続して投稿する場合には、X側の検知を避けるため30秒間の間隔を空けます。
- **定期実行**: 1時間に1回、`cron`（または同等のタスクスケジューラ）によって自動実行されるように設計されています。

## 技術スタック
- Python
- `selenium` (ツイート・リプライ取得、自動ログイン・投稿)
- `BeautifulSoup` & `requests` (必要に応じてHTML解析)
- `openai` (LLM連携、Geminiなど他のLLMも対応可能)
- `sqlite3` (データベース管理、ユーザー設定含む)

## ディレクトリ構成
```
Twitter_reply/
├── reply_bot/
│   ├─ main.py            # 全体制御スクリプト
│   ├─ csv_generator.py   # Selenium を使ったリプライ収集ロジック
│   ├─ thread_checker.py  # スレッドの起点投稿が自分自身か判定するロジック
│   ├─ gen_reply.py       # AIによる応答文生成とルール適用 (`is_my_thread`がTrueの場合のみ)
│   ├─ post_reply.py      # 返信投稿 (`is_my_thread`がTrueの場合のみ) と「いいね」を実行
│   ├─ add_user_preferences.py # ユーザーの呼び名などをDBに一括登録するスクリプト
│   ├─ config.py          # 各種設定（アカウント情報、APIキーなど）
│   ├─ db.py              # SQLite データベース操作
│   ├─ get_cookie.py      # Selenium を使ったCookieの保存と読み込み
│   └─ requirements.txt   # pip install 用依存リスト
├── cookie/
│   └── twitter_cookies_01.pkl
├── log/
│   └── replies_log_YYYYMMDD_HHMMSS.csv （各種ログファイル、Git追跡対象外）
├── source/
│   └── debug_page_source_NNN.html （デバッグ用HTMLソースファイル、Git追跡対象外）
├── output/
│   └── extracted_tweets_YYYYMMDD_HHMMSS.csv （抽出されたツイートデータ、Git追跡対象外）
└── .gitignore        # Git追跡対象外ファイル・フォルダ指定
```

## セットアップと実行

### 1. Conda環境のアクティベート
プロジェクトのスクリプトを実行する前に、Conda環境 `TwitterReplyEnv` をアクティベートしてください。

```bash
conda activate TwitterReplyEnv
```

### 2. 依存ライブラリのインストール
`requirements.txt` に記載されているPythonライブラリをインストールします。

```bash
pip install -r requirements.txt
```

### 3. ブラウザドライバーのインストール (Selenium)
Seleniumを使用するためには、WebDriver Managerをインストールすることをお勧めします。これにより、適切なブラウザドライバーが自動的にダウンロード・設定されます。

```bash
pip install webdriver-manager
```

### 4. `config.py` の設定
`reply_bot/config.py` を作成し、Xのアカウント情報やGemini APIキーなどを設定します。
このファイルはGit管理から除外することを推奨します（`.gitignore` に追加してください）。

```python
# reply_bot/config.py の例
TARGET_USER   = "nyukimi_AI"  # あなたのXユーザー名（@は不要）
LOGIN_URL     = "https://x.com/login"
USERNAME      = "nyukimi_AI" # Xのログインに使用するユーザー名またはメールアドレス
PASSWORD      = "USHIneko1" # Xのログインに使用するパスワード
GEMINI_API_KEY= "your-gemini-api-key" # Gemini APIキー
DB_PATH       = "replies.db"    # SQLiteデータベースのファイル名

# 注意: Mayaのパーソナリティや返信ルールに関するプロンプトは、
# 安全性と管理のしやすさから `reply_bot/gen_reply.py` スクリプト内で直接定義されています。

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

### 5. Cookieの取得と保存 (`get_cookie.py`) 
システムは初回ログイン時にCookieを保存し、次回以降のログインを自動化します。以下のスクリプトを実行し、手動でXにログインしてCookieを保存してください。

```bash
python -m reply_bot.get_cookie
```

### 6. ユーザー設定の初期登録（任意）
`reply_bot/add_user_preferences.py`スクリプトを使用して、初期ユーザー設定（呼び名など）をデータベースに登録できます。

```bash
python -m reply_bot.add_user_preferences
```

### 7. スクリプトの実行
全てのセットアップが完了したら、`main.py` を実行してシステムを起動します。

```bash
python -m reply_bot.main
```

### 8. 定期実行設定

システムを自動で実行するために、`cron`（Linux/macOS）またはタスクスケジューラ（Windows）に設定を追加します。

#### cron (Linux/macOS) の例:
`crontab -e` コマンドで設定ファイルを開き、以下の行を追加します。
（`/path/to/Twitter_reply` と `/path/to/conda/envs/TwitterReplyEnv/bin/python` はあなたの環境に合わせて変更してください）

```cron
# 毎時 0 分に main.py を実行
0 * * * * cd /path/to/Twitter_reply && /path/to/conda/envs/TwitterReplyEnv/bin/python reply_bot/main.py >> log/cron.log 2>&1
```

#### タスクスケジューラ (Windows) の例:
Windowsのタスクスケジューラを使用して、同様の設定を行います。

## 出力ファイル

スクリプトの実行により、以下のファイルが自動的に生成されます。

- `/log/replies_log_YYYYMMDD_HHMMSS.csv`: 取得されたリプライに関する詳細なログファイルです。実行日時がファイル名に含まれ、追記モードでログが記録されます。
- `/source/debug_page_source_NNN.html`: 各スクロール時のページHTMLソースが連番 (3桁) で保存されます。デバッグやHTML構造の分析に利用できます。
- `/output/extracted_tweets_YYYYMMDD_HHMMSS.csv`: 抽出されたツイートデータが保存されるCSVファイルです。スクリプト開始時に一度だけ生成され、実行完了までデータが追記されます。

これらのフォルダ (`log/`, `source/`, `output/`) は、`.gitignore` にてGitの追跡対象から除外されています。

## 注意事項
- エラーハンドリングとロギングは、デバッグと安定稼働のために重要です。
- `config.py` は機密情報を含むため、Git管理から除外してください。
- X側のレートリミットや自動検知を避けるため、Seleniumの操作速度や投稿間隔に注意してください。
- **ユーザー設定の活用**: `db.py`に`user_preferences`テーブルが追加され、`gen_reply.py`がこれを利用して、ユーザーの言語や呼び名に応じたパーソナライズされた応答を生成します。