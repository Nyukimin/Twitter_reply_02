import asyncio
import logging
import time
from typing import List, Dict
from . import db
from .gen_reply import generate
from .post_reply import post_reply

async def process_replies(replies_data: List[Dict]) -> None:
    """
    リプライデータを処理して返信を行います。
    
    Args:
        replies_data: 処理するリプライデータのリスト
    """
    logging.info(f"返信処理を開始します。対象リプライ数: {len(replies_data)}")
    
    processed_count = 0
    error_count = 0
    
    for reply in replies_data:
        reply_id = reply.get("reply_id")
        
        if not reply_id:
            logging.warning("リプライIDが見つかりません。スキップします。")
            continue
            
        if db.is_replied(reply_id):
            logging.info(f"リプライ {reply_id} はすでに返信済みです。スキップします。")
            continue
        
        try:
            logging.info(f"未返信リプライを検出しました: {reply_id}")
            
            # 応答文を生成
            reply_text = generate(
                reply.get("contents", ""), 
                reply.get("UserID", ""), 
                "ja",  # 言語は日本語固定
                None
            )
            logging.info(f"応答文を生成しました。内容: {reply_text[:50]}...")

            # 返信を投稿
            await post_reply(reply.get("reply_id"), reply_id, reply_text)
            
            # 返信済みとしてマーク
            db.mark_replied(
                reply_id, 
                reply.get("UserID", ""), 
                reply_text, 
                reply.get("is_my_thread", False)
            )
            
            logging.info(f"リプライ {reply_id} を投稿し、返信済みとしてマークしました。")
            processed_count += 1
            
            # 複数回投稿の間に10秒の間隔を空ける
            logging.info("次の投稿まで10秒待機します...")
            time.sleep(10)

        except Exception as e:
            logging.error(f"リプライ {reply_id} の処理中にエラーが発生しました: {e}")
            error_count += 1
    
    logging.info(f"返信処理が完了しました。")
    logging.info(f"  - 処理成功: {processed_count}件")
    logging.info(f"  - エラー: {error_count}件")

# この関数は main.py にロジックが移動したため不要
# async def process_priority_replies(replies_data: List[Dict], max_my_thread: int = 5, max_other_thread: int = 3) -> None:
#     """
#     優先度に基づいてリプライを処理します。
    
#     Args:
#         replies_data: リプライデータのリスト
#         max_my_thread: 自分のスレッドから処理する最大数
#         max_other_thread: 他人のスレッドから処理する最大数
#     """
#     from .thread_checker import get_priority_replies
    
#     # 優先度順にリプライを選択
#     priority_replies = get_priority_replies(replies_data, max_my_thread, max_other_thread)
    
#     # 選択されたリプライを処理
#     await process_replies(priority_replies) 