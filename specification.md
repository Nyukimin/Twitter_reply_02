# Maya自動返信ボット 仕様書 (v2.1)

## 1. 目的

本システムは、X（旧Twitter）上で「Maya（@Maya19960330）」アカウントに届いたメンション（リプライ）の中から、**自身の投稿を起点とするスレッドへの返信**を自動で特定し、AIによる返信文を生成、投稿準備までを行うことを目的とします。

## 2. システムアーキテクチャ

本システムは、複数の独立したPythonモジュールが、**CSVファイルやSQLiteデータベースを介して**順番に処理を受け渡すパイプラインアーキテクチャを採用しています。

```mermaid
graph TD;
    subgraph "事前準備"
        AA(add_user_preferences.py) --> DB[(user_preferences DB)];
    end

    A[Start] --> B(1. csv_generator.py);
    B -- extracted_tweets_...csv --> C(2. thread_checker.py);
    C -- priority_replies_...csv --> D(3. gen_reply.py);
    DB -.-> D;
    D -- generated_replies_...csv --> E(4. post_reply.py);
    E --> F[End];

    subgraph "制御"
        G(main.py)
    end

    G -.-> B;
    G -.-> C;
    G -.-> D;
    G -.-> E;
```

---

## 3. モジュール詳細

### ステップ0: ユーザー情報登録 (`add_user_preferences.py`)
-   **入力**: なし（スクリプト内で直接編集）
-   **処理**:
    -   特定のユーザー（友人など）のUserIDと、返信時に使用したいニックネーム、使用言語を`user_preferences`テーブルに登録します。
    -   このモジュールはパイプラインとは独立して、事前に手動で実行します。
-   **出力**: `replies.db`へのレコード追加

### ステップ1: リプライ収集 (`csv_generator.py`)

-   **入力**: なし
-   **処理**:
    -   Seleniumを起動し、Cookieを使ってXにログインします。
    -   通知ページ (`https://x.com/notifications/mentions`) にアクセスし、表示されるメンションから情報を抽出します。
    -   抽出項目: `reply_id`, `user_id`, `user_name`, `text`, `created_at`, `lang`
-   **出力**: `output/extracted_tweets_{タイムスタンプ}.csv`

### ステップ2: スレッド起点判定 (`thread_checker.py`)

-   **入力**: `extracted_tweets_...csv`
-   **処理**:
    -   入力CSVの各リプライについて、スレッドの大元の投稿者が自分自身 (`TARGET_USER`) かを判定します。
    -   判定結果を `is_my_thread` (True/False) 列に追加します。
-   **出力**: `output/priority_replies_rechecked_{タイムスタンプ}.csv`

### ステップ3: 返信文生成 (`gen_reply.py`)

-   **入力**: `priority_replies_rechecked_...csv`, `replies.db`
-   **処理**:
    -   `is_my_thread` が `True` のリプライを対象とします。
    -   リプライ投稿者のUserIDをキーに`user_preferences`テーブルを検索し、ニックネームが存在するか確認します。
    -   **ニックネームがある場合**: プログラムで「{ニックネーム}\n」を先頭につけ、AIには呼びかけを含まない親しみやすい返信を生成させます。
    -   **ニックネームがない場合**: AIに呼びかけなしの短い返信を生成させます。
    -   AIモデルにはGoogleのGemini (`gemini-1.5-flash`) を使用します。
    -   生成された返信文を `generated_reply` 列に追加します。
-   **出力**: `output/generated_replies_{タイムスタンプ}.csv`

### ステップ4: 投稿処理 (`post_reply.py`)

-   **入力**: `generated_replies_...csv`
-   **処理**:
    -   **ドライランモード (デフォルト)**:
        -   実際には投稿せず、「どのツイートに、どのような内容で返信し、いいねを押すか」という計画をログに出力します。
    -   **ライブモード (`--live-run` フラグ指定時)**:
        -   **【注意】実際にXへの投稿が行われます。**
        -   CSVの各行について、Seleniumで対象ツイートページにアクセスします。
        -   **`like_num`が0の場合に限り**、ツイートに「いいね」をします。
        -   `generated_reply` 列のテキストを使って、返信を投稿します（`Ctrl+Enter`キーを使用）。
-   **出力**: なし (ログ出力のみ)

### 統括制御 (`main.py`)

-   **役割**: 上記のステップ1〜4のモジュールを順番に呼び出し、処理全体の流れを制御します。
-   **処理フロー**:
    1.  `csv_generator.py` を実行
    2.  `thread_checker.py` を実行
    3.  `gen_reply.py` を実行
    4.  `post_reply.py` を実行 (常にドライランモード)

---

## 4. 設定ファイルとデータベース

### 設定ファイル (`config.py`)
-   `TARGET_USER`: 自分自身のXユーザーID (`@`なし)
-   `USERNAME`, `PASSWORD`: ログイン情報
-   `MAX_SCROLLS`: `csv_generator`での最大スクロール回数
-   `MAYA_PERSONALITY_PROMPT`: `gen_reply`でAIに与える人格設定プロンプト

### データベース (`replies.db`)
-   **`user_preferences`テーブル**: ニックネームや言語など、ユーザーごとの設定を保存します。

---

## 5. フォルダ構成

```
Twitter_reply/
├── reply_bot/
│   ├── main.py
│   ├── csv_generator.py
│   ├── thread_checker.py
│   ├── gen_reply.py
│   ├── post_reply.py
│   ├── add_user_preferences.py
│   ├── utils.py
│   ├── config.py
│   └── replies.db              # ユーザー情報などを格納
├── cookie/
│   └── twitter_cookies_01.pkl
├── output/
│   └── (各種CSVファイル)
└── requirements.txt
```
