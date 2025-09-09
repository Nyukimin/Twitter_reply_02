# Twitter自動返信ボット (v0.95)

## 概要
このシステムは、あなた（@nyukimi_AI）のX（旧Twitter）アカウントのツイートに対する他ユーザーからのリプライを自動的に検出し、AI（「Maya」）が文脈を理解した応答文を生成・投稿することを目的としています。**システムのコアは `reply_processor.py` に集約されており、単なる返信だけでなく、会話の文脈全体を考慮したインテリジェントな対話を実現します。**

---

## バージョン履歴

### **v0.95 (現在)**: ブラウザ表示モード制御機能の追加
- **ヘッドレスモード対応**: 全てのスクリプト（`main.py`, `csv_generator.py`, `reply_processor.py`, `post_reply.py`, `check_login_status.py`）に`--headless`オプションを追加。ブラウザを非表示で高速実行可能になりました。
- **デバッグ支援**: デフォルトはGUIモードのため、開発・デバッグ時はブラウザの動作を目視確認でき、本番運用時はヘッドレスモードで効率的に動作します。
- **運用の柔軟性向上**: `cron`等の定期実行では`--headless`を使用し、手動実行時はGUIで状況確認する使い分けが可能になりました。

### **v0.94**: インテリジェント返信処理への進化
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

#### 必須設定項目
`reply_bot/config.py`ファイルに以下の情報を設定してください：

```python
# reply_bot/config.py の設定例
TARGET_USER   = "nyukimi_AI"           # あなたのXアカウント名（@は不要）
LOGIN_URL     = "https://x.com/login"  # ログインURL（通常変更不要）
USERNAME      = "your_username"        # Xのログインに使用するユーザー名またはメールアドレス
PASSWORD      = "your_password"        # Xのログインに使用するパスワード
GEMINI_API_KEY= "your_gemini_api_key"  # Google Gemini APIキー

# データベース設定
DB_FILE       = "replies.db"           # SQLiteデータベースのファイル名

# プロファイル設定
PROFILES_DIR  = "./profiles"           # Chromeプロファイル保存ディレクトリ

# 多言語対応の感謝フレーズ
THANK_YOU_PHRASES = {
    "en": ["thanks❤", "Thank you so much!❤", "I appreciate it!❤", "Thanks a lot!❤"],
    "es": ["Gracias❤", "¡Muchas gracias!❤", "Te lo agradezco❤", "¡Mil gracias!❤"],
    "ja": ["ありがとう❤", "感謝です❤", "ありがとうございます❤"],
    # ... 他の言語も同様に複数パターンを定義 ...
}
```

**⚠️ 重要**: USERNAME と PASSWORD は必須項目です。初回実行時にこれらの情報を使ってTwitterにログインし、以降はChromeプロファイルで自動ログインされます。

**具体的な設定例**:
```python
# 実際の設定例
TARGET_USER   = "maya19960330"          # あなたのXアカウント名
USERNAME      = "maya@example.com"      # ログインに使うメールアドレス
PASSWORD      = "your_strong_password"  # Xのパスワード
GEMINI_API_KEY= "AIzaSyA7aSuSGwd..."    # Gemini APIキー（詳細は下記参照）
```

#### Gemini API キーの取得方法
1. [Google AI Studio](https://makersuite.google.com/app/apikey)にアクセス
2. 「Create API Key」をクリック
3. 生成されたAPIキーを`GEMINI_API_KEY`に設定

### 3.5. システム要件とトラブルシューティング

#### Chrome関連のトラブルシューティング
システムが`SessionNotCreatedException`や`user data directory is already in use`エラーを出す場合、以下の手順で解決します：

**Windows環境での対処法：**
```powershell
# 1. PowerShellを管理者権限で開き、残骸プロセスを停止
taskkill /f /im chrome.exe /im msedge.exe /im chromedriver.exe

# 2. プロファイルディレクトリのロックファイルを削除
del "C:\GenerativeAI\Twitter_reply_02\profiles\twitter_main\Singleton*"
del "C:\GenerativeAI\Twitter_reply_02\profiles\twitter_main_*\Singleton*"
```

**Linux/macOS環境での対処法：**
```bash
# 残骸プロセスを停止
pkill -f chrome
pkill -f chromedriver

# ロックファイルを削除
rm -f ./profiles/*/Singleton*
```

#### Chrome設定の最適化
Chromeの「バックグラウンドで実行」を無効化することを推奨します：
1. Chromeを手動で開く
2. 設定 → 詳細設定 → システム
3. 「Google Chrome を閉じた際にバックグラウンド アプリの処理を続行する」を**オフ**

#### 環境変数の設定
システムの安定性を向上させるため、以下の環境変数を設定してください：

**Windows（コマンドプロンプト）：**
```cmd
set DISPLAY=:0
set CHROME_NO_SANDBOX=1
```

**Linux/macOS：**
```bash
export DISPLAY=:0
export CHROME_NO_SANDBOX=1
```

#### セキュリティソフトの除外設定
使用しているウイルス対策ソフトで、以下のディレクトリを監視対象外に設定してください：
- `C:\GenerativeAI\Twitter_reply_02\profiles\` (プロファイルディレクトリ)
- `%LOCALAPPDATA%\Temp\` (一時ファイル)

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

#### 自動クリーンアップ付き実行（Windows推奨）

Windows環境でChromeプロファイルのロック問題を回避するため、自動クリーンアップスクリプトを使用することを推奨します：

```bash
# コマンドプロンプトから実行（推奨）
run_with_cleanup.bat --debug

# PowerShellから実行する場合
cmd /c "run_with_cleanup.bat --debug"
# または
.\run_with_cleanup.bat --debug

# PowerShell版（詳細なログ付き）
powershell -ExecutionPolicy Bypass -File .\run_with_cleanup.ps1
```

これらのスクリプトは以下を自動的に実行します：
1. 特定プロファイルのChromeプロセスのみを終了（他のChromeは影響なし）
2. ChromeDriverプロセスを終了
3. ロックファイルを削除
4. メインプログラムを起動

#### 基本的な実行方法
全てのセットアップが完了したら、`main.py` を実行します。
```bash
# ドライランモード（デフォルト）- 投稿やいいねを行わずにテスト実行
python -m reply_bot.main

# ライブモード - 実際に投稿やいいねを実行
python -m reply_bot.main --live-run
```

#### ブラウザ表示モードの制御
v0.95から、各スクリプトで**ブラウザの表示/非表示を選択**できるようになりました。

**ブラウザ表示モード（GUI）** - デバッグや動作確認に最適：
```bash
# メイン処理（デフォルトでブラウザ表示）
python -m reply_bot.main

# 各個別モジュールも同様
python -m reply_bot.csv_generator
python -m reply_bot.reply_processor input.csv
python -m reply_bot.post_reply input.csv
python -m reply_bot.check_login_status
```

**ヘッドレスモード（非表示）** - 本番運用や高速処理に最適：
```bash
# メイン処理をヘッドレスモードで実行
python -m reply_bot.main --headless

# リプライ収集をヘッドレスモードで実行
python -m reply_bot.csv_generator --headless

# スレッド解析と返信生成をヘッドレスモードで実行
python -m reply_bot.reply_processor input.csv --headless

# 投稿処理をヘッドレスモードで実行
python -m reply_bot.post_reply input.csv --headless

# ログイン状態確認をヘッドレスモードで実行
python -m reply_bot.check_login_status --headless
```

#### 実行オプションの詳細

**`main.py`** - メインコントローラー（全処理を自動実行）
```bash
# 基本形式
python -m reply_bot.main [オプション]

# 利用可能オプション
--timestamp YYYYMMDD_HHMMSS  # 出力ファイル名のタイムスタンプを指定
--hours N                    # 過去N時間のリプライのみ収集
--live-run                   # ドライランを無効化し、実際に投稿・いいねを実行
--headless                   # ブラウザを非表示で起動

# 実行例
python -m reply_bot.main --hours 12 --headless --live-run
```

**`csv_generator.py`** - リプライ収集モジュール
```bash
# 基本形式
python -m reply_bot.csv_generator [オプション]

# 利用可能オプション
--output PATH               # 出力CSVファイルのパス指定
--scrolls N                 # 最大スクロール回数（デフォルト: 100）
--pixels N                  # 1回のスクロール量（デフォルト: 3000px）
--hours N                   # 過去N時間のリプライのみ収集
--headless                  # ブラウザを非表示で起動

# 実行例：過去6時間のリプライを高速収集
python -m reply_bot.csv_generator --hours 6 --headless --scrolls 50
```

**`reply_processor.py`** - スレッド解析・返信生成モジュール
```bash
# 基本形式
python -m reply_bot.reply_processor INPUT_CSV [オプション]

# 利用可能オプション
--limit N                   # 処理するリプライの最大数
--headless                  # ブラウザを非表示で起動

# 実行例：最大20件のリプライを処理
python -m reply_bot.reply_processor output/extracted_tweets_20250107_120000.csv --limit 20 --headless
```

**`post_reply.py`** - 投稿・いいね実行モジュール
```bash
# 基本形式
python -m reply_bot.post_reply INPUT_CSV [オプション]

# 利用可能オプション
--live-run                  # ドライランを無効化し、実際に投稿・いいねを実行
--limit N                   # 処理するツイートの最大数
--interval N                # 投稿間の待機時間（秒）
--headless                  # ブラウザを非表示で起動

# 実行例：5件まで実際に投稿、10秒間隔
python -m reply_bot.post_reply output/processed_replies_20250107_120000.csv --live-run --limit 5 --interval 10 --headless
```

**`check_login_status.py`** - ログイン状態確認モジュール
```bash
# 基本形式
python -m reply_bot.check_login_status [オプション]

# 利用可能オプション
--headless                  # ブラウザを非表示で起動

# 実行例：ヘッドレスモードでログイン状態確認
python -m reply_bot.check_login_status --headless
```

### 7. 定期実行設定
`cron`（Linux/macOS）やタスクスケジューラ（Windows）で定期的に実行するよう設定します。本番環境では**ヘッドレスモード**での実行を推奨します。

#### Linux/macOS (cron)
```bash
# crontabを編集
crontab -e

# 毎時0分に main.py をライブモード + ヘッドレスモードで実行
0 * * * * cd /path/to/Twitter_reply_02 && /path/to/conda/envs/TwitterReplyEnv/bin/python -m reply_bot.main --live-run --headless >> /path/to/Twitter_reply_02/log/cron.log 2>&1

# より細かい制御が必要な場合の例（過去2時間のデータのみ処理）
0 */2 * * * cd /path/to/Twitter_reply_02 && /path/to/conda/envs/TwitterReplyEnv/bin/python -m reply_bot.main --hours 2 --live-run --headless >> /path/to/Twitter_reply_02/log/cron.log 2>&1
```

#### Windows (タスクスケジューラ)
1. `タスクスケジューラ`を開く
2. `基本タスクの作成`を選択
3. 以下の設定を入力：
   - **名前**: Twitter Reply Bot
   - **トリガー**: 毎日、1時間ごと
   - **操作**: プログラムの開始
   - **プログラム**: `C:\path\to\conda\envs\TwitterReplyEnv\python.exe`
   - **引数**: `-m reply_bot.main --live-run --headless`
   - **開始**: `C:\GenerativeAI\Twitter_reply_02`

#### Windows (バッチファイルを使用)
`run_twitter_bot.bat`を作成：
```batch
@echo off
cd /d "C:\GenerativeAI\Twitter_reply_02"
call conda activate TwitterReplyEnv
python -m reply_bot.main --live-run --headless >> log\cron.log 2>&1
```

## 出力ファイル
`/output` フォルダに、処理結果のCSVファイル (`replies_YYYYMMDD_HHMMSS.csv`) が生成されます。このファイルには、収集したツイート、生成した返信、AIの思考プロセス、投稿結果などがすべて記録されます。

---

## 完全セットアップガイド（初回設定）

### ステップ1: Conda環境の準備
```bash
# 1. Conda環境の作成
conda create -n TwitterReplyEnv python=3.9

# 2. 環境のアクティベート
conda activate TwitterReplyEnv

# 3. 必要ライブラリのインストール
pip install selenium webdriver-manager beautifulsoup4 google-generativeai pandas sqlite3 psutil
```

### ステップ2: プロジェクトのクローン
```bash
# GitHubからクローン
git clone https://github.com/Nyukimin/Twitter_reply_02.git
cd Twitter_reply_02
```

### ステップ3: 設定ファイルの作成
```bash
# config.pyを編集して、必要な情報を入力
# Windows の場合
notepad reply_bot/config.py

# Linux/macOS の場合
nano reply_bot/config.py
# または
vim reply_bot/config.py
```

**設定必須項目チェックリスト**:
- [ ] `TARGET_USER`: あなたのXアカウント名（@なし）
- [ ] `USERNAME`: ログインに使うユーザー名またはメールアドレス
- [ ] `PASSWORD`: Xのパスワード
- [ ] `GEMINI_API_KEY`: Google Gemini APIキー

**設定例**:
```python
TARGET_USER   = "your_account_name"
USERNAME      = "your_email@example.com"    # またはユーザー名
PASSWORD      = "your_twitter_password"
GEMINI_API_KEY= "AIzaSyA7aSuSGwd..."        # Gemini APIキー
```

### ステップ4: 初回ログインとプロファイル作成
```bash
# 手動ログインでプロファイルを作成
python -m reply_bot.check_login_status
```
このコマンドを実行すると：
1. Chromeが起動してTwitterのログイン画面が表示されます
2. 手動でTwitterアカウントにログイン
3. ログイン情報がChromeプロファイル（`profiles/twitter_main/`）に自動保存されます
4. 以降の実行では自動的にログイン状態が維持されます

### ステップ5: データベースの初期化
```bash
# ユーザー設定DB（オプション）
python -m reply_bot.add_user_preferences
```

### ステップ6: 動作テスト
```bash
# ログイン状態の確認
python -m reply_bot.check_login_status

# ドライランでテスト実行
python -m reply_bot.main

# 正常に動作することを確認後、ライブモードテスト
python -m reply_bot.main --live-run --limit 1
```

## よくある問題と解決方法

### Q1: Chrome起動エラー（SessionNotCreatedException）
**A1**: 残骸プロセスとロックファイルをクリーンアップ
```powershell
# Windows
taskkill /f /im chrome.exe /im chromedriver.exe
del "profiles\*\Singleton*"

# Linux/macOS
pkill chrome; pkill chromedriver
rm -f profiles/*/Singleton*
```

### Q2: ログインが維持されない
**A2**: Cookieの再取得が必要
```bash
python -m reply_bot.get_cookie
```

### Q3: Gemini APIエラー
**A3**: APIキーとクォータの確認
- [Google AI Studio](https://makersuite.google.com/app/apikey)でAPIキーを確認
- APIの使用量制限を確認

### Q4: 「プロファイルが使用中」エラー
**A4**: 自動修復機能が働きます。それでも解決しない場合：
```bash
# 全ての一時プロファイルをクリーンアップ
rm -rf profiles/_temp/
```

### Q5: メモリ不足でクラッシュ
**A5**: ヘッドレスモードを使用し、処理件数を制限
```bash
python -m reply_bot.main --headless --limit 10
```

## サポートとデバッグ

### ログの確認
- メインログ: `log/main_process.log`
- 個別ログ: `log/` フォルダ内の各ファイル

### デバッグモード
```bash
# ブラウザを表示してデバッグ
python -m reply_bot.main --limit 1

# 詳細ログ付きで実行
python -m reply_bot.main --headless --limit 1 2>&1 | tee debug.log
```

### パフォーマンス最適化
```bash
# 高速処理モード（過去2時間のみ、ヘッドレス、制限付き）
python -m reply_bot.main --hours 2 --headless --limit 5 --live-run
```