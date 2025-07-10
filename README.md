# Twitter自動返信ボット (v0.94)

## 概要
このシステムは、あなた（@nyukimi_AI）のX（旧Twitter）アカウントのツイートに対する他ユーザーからのリプライを自動的に検出し、AI（「Maya」）が文脈を理解した応答文を生成・投稿することを目的としています。**システムのコアは `reply_processor.py` に集約されており、単なる返信だけでなく、会話の文脈全体を考慮したインテリジェントな対話を実現します。**

---

## バージョン履歴

### **v0.94 (現在)**: インテリジェント返信処理への進化
- **アーキテクチャ刷新**: `thread_checker.py`と`gen_reply.py`を廃止し、スレッド解析、AIによる返信生成、投稿前チェックの全機能を`reply_bot/reply_processor.py`に統合。処理が効率化され、モジュール間の依存関係が簡潔になりました。
- **AIの文脈理解能力の向上**: AIにスレッド全体の会話履歴を渡すことで、より文脈に沿った自然な返信が可能になりました。
- **返信の多様性向上**:
    - **動的禁止ワード**: AIが自己模倣に陥るのを防ぐため、過去の返信で使われた動詞・形容詞を「禁止ワード」として動的にプロンプトへ追加する機能を実装。
    - **定型文の拡充**: 短い挨拶や外国語への返信が単調にならないよう、複数パターンの感謝フレーズを`config.py`で管理し、ランダムに選択して使用するように改善。
- **堅牢な投稿ルール**:
    - **最優先返信ルール**: 「自分のスレッドへの最初の返信(`reply_num=0` and `is_my_thread=True`)」には、後続ツイートがあっても必ず返信するルールを実装。判定はCSVの情報ではなく、処理実行時の**ライブ情報**で行われます。
    - **ライブ情報のCSV反映**: スキップされたツイートについても、スキップ判断の根拠となったライブの「返信件数」「いいね数」を最終的なCSVに記録し、データの正確性を向上させました。

### **v0.9**: 重複投稿チェック機能の堅牢化
- **動的な重複投稿チェック**: `post_reply.py`に、返信対象のツイートページを直接開き、そのツイートよりも**後**に誰かの返信が既に存在するかをリアルタイムで確認する機能を追加。後続の返信がある場合は会話への割り込みと判断し、投稿をスキMップするようにしました。

### **v0.8**: 基本機能の実装
- **パイプライン処理**: `csv_generator` -> `thread_checker` -> `gen_reply` -> `post_reply`という、各機能が独立したモジュールとしてCSVファイルを介して連携するアーキテクチャでした。
- **基本的な返信機能**: 自分のスレッド(`is_my_thread=True`)への返信に対して、AIが応答を生成し、投稿する基本機能を実装していました。

---

## 主な機能
- **X API不使用**: `selenium` を活用し、コストをかけずに運用します。
- **リプライ・ツイート取得**: 通知ページからメンションを抽出し、分析のベースとなるデータを作成します。
- **インテリジェントな返信生成 (`reply_processor.py`)**:
    - **スレッド文脈理解**: 会話全体の流れを読み解き、AIが自然な応答を生成します。
    - **多様な返信ロジック**:
        - **ニックネーム呼びかけ**: DB登録済みの「顔なじみ」ユーザーにはニックネームで呼びかけます。
        - **多言語対応の定型文**: 短い挨拶や絵文字のみのツイートには、言語を判定し、`config.py`に定義された複数の定型フレーズからランダムに返信します。
        - **自己模倣防止**: 過去の返信で多用した表現を避け、常に新鮮な言葉で応答します。
- **堅牢な自動投稿 (`post_reply.py`)**:
    - **ライブ情報に基づく重複投稿チェック**: ページの**ライブ情報**を元に、会話への割り込みを厳密に判定し、不要な投稿をスキップします。
    - **最優先ルールの適用**: 「自分のスレッドへの初リプライ」という最重要ケースを見逃さずに返信します。
    - **状態管理による重複「いいね」防止**: 「いいね」の状態をCSVで管理し、重複アクションを防ぎます。
- **ユーザー設定**: `sqlite3`データベースで、ユーザーごとのニックネームなどを管理します。
- **定期実行**: `cron`等で1時間ごとに自動実行される設計です。

## 技術スタック
- Python
- `selenium` / `webdriver-manager`
- `BeautifulSoup`
- `google-generativeai` (Gemini)
- `sqlite3`
- `pandas`

## ディレクトリ構成
```
Twitter_reply/
├── reply_bot/
│   ├─ main.py            # 全体制御スクリプト
│   ├─ csv_generator.py   # Selenium を使ったリプライ収集ロジック
│   ├─ reply_processor.py # ★(New) スレッド分析・返信生成・ルール適用のコアモジュール
│   ├─ post_reply.py      # 返信投稿と「いいね」を実行
│   ├─ add_user_preferences.py # ユーザー設定をDBに一括登録
│   ├─ config.py          # 各種設定（アカウント情報、APIキーなど）
│   ├─ db.py              # SQLite データベース操作
│   ├─ get_cookie.py      # Cookieの保存と読み込み
│   └─ requirements.txt   # 依存ライブラリ
├── cookie/
├── log/
├── source/
├── output/
└── .gitignore
```
*`thread_checker.py` と `gen_reply.py` は `reply_processor.py` に統合され、廃止されました。*

## セットアップと実行

### 1. Conda環境のアクティベート
```bash
conda activate TwitterReplyEnv
```

### 2. 依存ライブラリのインストール
```bash
pip install -r reply_bot/requirements.txt
```

### 3. `config.py` の設定
`reply_bot/config.py` に、Xのアカウント情報やGemini APIキーなどを設定します。
```python
# reply_bot/config.py の例
TARGET_USER = "nyukimi_AI"
LOGIN_URL = "https://x.com/login"
USERNAME = "..."
PASSWORD = "..."
GEMINI_API_KEY = "..."
DB_PATH = "replies.db"

# 多言語対応の感謝フレーズ
THANK_YOU_PHRASES = {
    "en": ["thanks❤", "Thank you so much!❤", "I appreciate it!❤", "Thanks a lot!❤"],
    "es": ["Gracias❤", "¡Muchas gracias!❤", "Te lo agradezco❤", "¡Mil gracias!❤"],
    # ... 他の言語も同様に複数パターンを定義 ...
}
```

### 4. Cookieの取得と保存
初回実行時のみ、以下のコマンドで手動ログインし、Cookieを保存します。
```bash
python -m reply_bot.get_cookie
```

### 5. ユーザー設定の初期登録（任意）
```bash
python -m reply_bot.add_user_preferences
```

### 6. スクリプトの実行
全てのセットアップが完了したら、`main.py` を実行します。
```bash
python -m reply_bot.main
```
デフォルトでは、投稿や「いいね」を行わない**ドライランモード**で実行されます。実際に投稿するには `--live-run` フラグを追加します。
```bash
python -m reply_bot.main --live-run
```

### 7. 定期実行設定
`cron`（Linux/macOS）やタスクスケジューラ（Windows）で定期的に実行するよう設定します。
```cron
# 毎時0分に main.py をライブモードで実行
0 * * * * cd /path/to/Twitter_reply && /path/to/conda/envs/TwitterReplyEnv/bin/python -m reply_bot.main --live-run >> /path/to/Twitter_reply/log/cron.log 2>&1
```

## 出力ファイル
`/output` フォルダに、処理結果のCSVファイル (`replies_YYYYMMDD_HHMMSS.csv`) が生成されます。このファイルには、収集したツイート、生成した返信、AIの思考プロセス、投稿結果などがすべて記録されます。