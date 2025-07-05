# Maya自動返信ボット仕様書（スレッド起点判定対応）

## 目的
本システムは、X（旧Twitter）上で「Maya（@Maya19960330）」アカウントに届いたリプライに対して、未返信のものへ自動的に返信を投稿することを目的とする。  
さらに、**リプライがスレッド形式（会話の途中）である場合、その起点となる元ツイートが自分（Maya）の投稿であるかどうかをたどって確認する機能**を持つ。

---

## 全体構成

### 1. リプライ収集
- 利用ライブラリ：`selenium` によるブラウザ自動操作（`snscrape` は使用しない）
- 操作対象：Twitterの通知ページ（https://twitter.com/notifications/mentions）
- 処理内容：
  - リプライ一覧を抽出
  - HTML構造から以下を取得：
    - リプライしたユーザーID
    - リプライ本文
    - リプライ元ツイートのURL、ツイートID
    - **そのリプライ元がさらにリプライである場合、順にたどる**
    - **スレッドの最初のツイート（起点）が自分の投稿かどうかを判定**
  - **各スクロール後のHTMLソースを `/source/debug_page_source_NNN.html` (3桁の連番) の形式で保存する**
  - **重複するリプライIDをスキップし、既に処理済みのリプライは再度追加しない**
  - **抽出結果は `/output/extracted_tweets_YYYYMMDD_HHMMSS.csv` ファイルに、実行開始時に一度だけ作成され、追記モードで保存される**
  - **スクロール量は、ウィンドウの高さの80%をスクロールすることで20%の重複を目指す（適応的調整は今後の検討課題）**

#### 1.1. 0ページ目（初回ページ）処理
- **通知ページアクセス後、5秒待機**してページの完全ロードを確保
- **0ページ目のHTMLソースを `/source/debug_page_source_000.html` として保存**
- **0ページ目のデータ抽出・CSV出力**を実行
- **重複チェック**も0ページ目で適用

#### 1.2. スクロール設定
- **最大スクロール回数：100回（config.pyで設定可能）**
- **引数化対応**：`fetch_replies(target_user, output_csv_path, max_scrolls=100)`
- **main関数引数化**：`main(max_scrolls=100)`
- **設定ファイル連携**：`config.py`の`MAX_SCROLLS`でデフォルト値管理

### 2. 起点ツイート判定ロジック
- 対象リプライが「リプライ to リプライ」であれば、`in_reply_to_status_id` をたどる
- 最終的にたどり着いた「起点ツイート」の投稿者が `@Maya19960330` かを確認
- 判定結果を元に、返信方針を以下のように分岐する：

| スレッド起点 | 返信方針 |
|--------------|----------|
| Mayaの投稿   | 通常どおり返信する（関与OK） |
| 他人の投稿   | 返信を控える、または内容を柔らかく調整する |

---

## 3. 未返信判定
- 利用：`replies.db`（SQLite）に記録された返信済みデータと照合
- 一致条件：ツイートIDがDBに存在しない場合 → 未返信とみなす

---

## 4. 自動返信文の生成
- 使用モジュール：`gen_reply.py`
- 返信のトーン：Mayaの人格（癒し・自然・少し色気）に基づく
- **起点が他人の場合は、あえて「敬語のみ」「丁寧だが薄めの反応」などに切り替えることも可能**

---

## 5. Seleniumによる投稿とCookie認証

- Cookieは `.pkl` ファイルで保存（初回は `get_cookie.py` にて手動ログイン後に取得）
- 投稿処理は `post_reply.py` にて行い、ログイン状態を維持したままツイートに返信

---

## データベース構成（replies.db）

| カラム名       | 内容                             |
|----------------|----------------------------------|
| tweet_id       | リプライ対象のツイートID（数値）   |
| user_id        | ユーザーIDまたはスクリーンネーム     |
| reply_text     | 返信した本文                       |
| is_my_thread   | boolean（True = 起点が自分）        |
| timestamp      | 投稿日時（ISOフォーマット）         |

---

## 設定ファイル（config.py）

### 基本設定
```python
TARGET_USER   = "nyukimi_AI"  # 対象ユーザー名
MAX_SCROLLS   = 100           # 最大スクロール回数
```

### スクロール設定
- **デフォルト値**：100回
- **設定方法**：`config.py`の`MAX_SCROLLS`で変更
- **実行時指定**：`main(max_scrolls=50)`で個別指定可能

---

## スケジュール実行
- 毎日1回またはN分ごとの実行を想定（`main.py`からバッチ起動可能）
- 実行後にログファイル（`/log/replies_log_YYYYMMDD_HHMMSS.csv`）に処理履歴を保存

---

## フォルダ構成例

```
Twitter_reply/
├── reply_bot/
│   ├── main.py
│   ├── fetch.py（Selenium使用、スレッド判定含む）
│   ├── gen_reply.py
│   ├── post_reply.py
│   ├── get_cookie.py
│   ├── db.py
│   ├── config.py
│   ├── ...
├── cookie/
│   └── twitter_cookies_01.pkl
├── log/
│   └── replies_log_YYYYMMDD_HHMMSS.csv （ログファイル、Git追跡対象外）
├── source/
│   ├── debug_page_source_000.html （0ページ目、Git追跡対象外）
│   └── debug_page_source_NNN.html （スクロール後、Git追跡対象外）
├── output/
│   └── extracted_tweets_YYYYMMDD_HHMMSS.csv （抽出されたツイートデータ、Git追跡対象外）
└── requirements.txt
```

---

## 処理フロー詳細

### 1. 初期化処理
```
1. データベース初期化（db.init_db()）
2. ログ設定
3. 出力ディレクトリ作成
4. CSVファイル名生成
```

### 2. 0ページ目処理
```
1. 通知ページアクセス
2. WebDriverWaitでツイート要素確認（30秒タイムアウト）
3. 5秒待機（ページ完全ロード）
4. HTML保存（debug_page_source_000.html）
5. データ抽出・CSV出力
6. 重複チェック
```

### 3. スクロール処理
```
1. スクロール実行（ウィンドウ高さの80%）
2. 5秒待機（コンテンツロード）
3. HTML保存（debug_page_source_001.html, 002.html, ...）
4. データ抽出・CSV出力
5. 重複チェック
6. 最大スクロール回数または新コンテンツなしで停止
```

---

## 使用ライブラリ

- `selenium`
- `beautifulsoup4`
- `sqlite3`
- `openai`（任意）
- `pytz`（タイムゾーン処理）
- `pathlib`（ファイルパス処理）
