import subprocess
import json
import logging
from datetime import datetime, timedelta
from .config import TARGET_USER

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_replies(target_user: str) -> list[dict]:
    """
    snscrapeを使用して、指定ユーザーのツイートに対するリプライを取得します。
    直近24時間のリプライのみを対象とします。
    
    Args:
        target_user (str): リプライを取得したいユーザーのX（旧Twitter）ID（@なし）。

    Returns:
        list[dict]: 以下の形式のリプライデータのリスト。
                    [
                      {"tweet_id": "返信元のツイートID", "reply_id": "リプライ自身のID", "content": "リプライの本文"},
                      ...
                    ]
    """
    replies_data = []
    
    # snscrape コマンドの構築
    # 'to:target_user' で target_user へのメンションやリプライを含むツイートを検索
    # `--jsonl` でJSON Lines形式の出力を得る
    query = f"to:{target_user}"
    command = ["snscrape", "--jsonl", "twitter-search", query]

    logging.info(f"snscrape コマンドを実行中: {' '.join(command)}")

    try:
        # CLIコマンドを実行し、標準出力をキャプチャ
        process = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        
        now = datetime.now()
        twenty_four_hours_ago = now - timedelta(hours=24)

        for line in process.stdout.splitlines():
            try:
                tweet = json.loads(line)
                
                # リプライが24時間以内であるかチェック
                tweet_datetime_str = tweet.get('date')
                if not tweet_datetime_str:
                    logging.warning(f"ツイートに日付フィールドがありません: {tweet.get('id')}")
                    continue

                # ISOフォーマットの日付文字列をdatetimeオブジェクトに変換
                # snscrapeのdateはUTCであることが多いため、タイムゾーン情報が正確であることを確認
                tweet_datetime = datetime.fromisoformat(tweet_datetime_str)
                
                if tweet_datetime < twenty_four_hours_ago:
                    continue # 24時間以上前のリプライはスキップ

                # target_userのツイートに対する直接のリプライであるかを判断
                # inReplyToTweetId が存在し、かつ inReplyToUser の username が target_user と一致する場合
                if ('inReplyToTweetId' in tweet and tweet['inReplyToTweetId'] is not None and
                    'inReplyToUser' in tweet and tweet['inReplyToUser'] is not None and
                    'username' in tweet['inReplyToUser'] and
                    tweet['inReplyToUser']['username'].lower() == target_user.lower()):
                    
                    replies_data.append({
                        "tweet_id": str(tweet['inReplyToTweetId']), # 返信元のツイートID
                        "reply_id": str(tweet['id']),                # リプライ自身のID
                        "content": tweet['renderedContent']          # リプライの本文
                    })
            except json.JSONDecodeError as e:
                logging.error(f"JSON解析エラー: {e} - 行: {line}")
            except KeyError as e:
                logging.warning(f"snscrape出力に予期せぬキーが見つかりません: {e} - ツイートデータの一部: {line[:100]}...")
            except ValueError as e: # datetime.fromisoformatのエラーハンドリング
                logging.error(f"日付解析エラー: {e} - 日付文字列: {tweet_datetime_str} - 行: {line}")

    except subprocess.CalledProcessError as e:
        logging.error(f"snscrape コマンドがエラーコード {e.returncode} で失敗しました: {e.stderr}")
        logging.error(f"標準エラー出力: {e.stderr}")
    except FileNotFoundError:
        logging.error("snscrape コマンドが見つかりません。インストールされているか、PATHが通っているか確認してください。")

    return replies_data

if __name__ == "__main__":
    # テスト実行用のダミーユーザー名
    # 実際の運用ではconfig.pyからTARGET_USERをインポートして使用
    # from config import TARGET_USER
    
    # 開発環境でテストする際は、一時的に有効なユーザー名に置き換えてください。
    # 例: test_user = "ren_ai_coach"
    test_user = "test_user_for_snscrape"

    logging.info(f"ユーザー {test_user} のリプライを取得中...")
    sample_replies = fetch_replies(test_user)
    
    if sample_replies:
        logging.info(f"過去24時間で {len(sample_replies)} 件のリプライを取得しました:")
        for reply in sample_replies[:5]: # 最初の5件のみ表示
            logging.info(reply)
    else:
        logging.info(f"過去24時間で {test_user} のリプライは見つかりませんでした。") 