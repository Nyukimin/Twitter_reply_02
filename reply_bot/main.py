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