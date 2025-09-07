import logging
import os
from datetime import datetime
import argparse # argparseをインポート

# 各モジュールのメイン処理関数をインポート
from .csv_generator import main_process as csv_generator_main
from .reply_processor import main_process as reply_processor_main
from .post_reply import main_process as post_reply_main
from .config import HOURS_TO_COLLECT, POST_INTERVAL_SECONDS
from .utils import setup_driver, close_driver

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main(timestamp_str: str | None = None, hours_arg: int | None = None, live_run: bool = False, headless: bool = False):
    """
    自動返信システムのメイン処理フローを制御します。
    """
    logging.info("=== 自動返信システムを開始します ===")
    
    driver = None
    try:
        # 最初にWebDriverを一度だけセットアップ
        driver = setup_driver(headless=headless)
        if not driver:
            logging.error("WebDriverの初期化に失敗しました。処理を中断します。")
            return

        # --------------------------------------------------------------------------
        # ステップ1: 通知ページからリプライを取得し、CSVを生成
        # --------------------------------------------------------------------------
        logging.info("--- [ステップ1/3] リプライの取得とCSV生成を開始します ---")
        
        # タイムスタンプの決定ロジック
        if timestamp_str:
            timestamp = timestamp_str
            logging.info(f"指定されたタイムスタンプを使用します: {timestamp}")
        else:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            logging.info(f"新しいタイムスタンプを生成しました: {timestamp}")

        initial_csv_path_template = os.path.join('output', f'extracted_tweets_{timestamp}.csv')
        
        # 引数で時間が指定されていればそれを使い、なければconfigから読み込む
        hours_to_use = hours_arg if hours_arg is not None else HOURS_TO_COLLECT
        logging.info(f"データ収集期間: 過去 {hours_to_use} 時間")

        initial_csv_path = csv_generator_main(
            driver=driver,
            output_csv_path=initial_csv_path_template, 
            hours_to_collect=hours_to_use
        )
        
        if not initial_csv_path or not os.path.exists(initial_csv_path):
            logging.error("ステップ1でCSVファイルが生成されませんでした。処理を中断します。")
            return
        logging.info(f"リプライ一覧を {initial_csv_path} に保存しました。")
        
        
        # --------------------------------------------------------------------------
        # ステップ2: スレッド解析と返信生成
        # --------------------------------------------------------------------------
        logging.info("--- [ステップ2/3] スレッド解析と返信生成を開始します ---")
        processed_csv_path = reply_processor_main(driver, initial_csv_path)
        
        if not processed_csv_path or not os.path.exists(processed_csv_path):
            logging.warning("ステップ2で処理済みCSVファイルが生成されませんでした。後続処理をスキップします。")
            logging.info("=== 自動返信システムを終了します ===")
            return
        logging.info(f"スレッド解析と返信生成の結果を {processed_csv_path} に保存しました。")
            

        # --------------------------------------------------------------------------
        # ステップ3: いいね＆返信投稿 (デフォルトはドライラン)
        # --------------------------------------------------------------------------
        logging.info("--- [ステップ3/3] いいねと返信の投稿処理を開始します ---")
        # live_runフラグに基づいてドライランまたは実際の投稿を実行
        is_dry_run = not live_run
        if live_run:
            logging.warning("*** LIVE-RUN モードで実行します。実際に投稿・いいねが行われます ***")
        else:
            logging.info("ドライランモードで実行します。実際の投稿・いいねは行われません。")
        post_reply_main(driver, processed_csv_path, dry_run=is_dry_run, interval=POST_INTERVAL_SECONDS)
        
        logging.info("=== 全ての処理が正常に完了しました ===")
    
    except Exception as e:
        logging.error(f"メイン処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        # 全ての処理が終了したら、WebDriverを閉じる
        logging.info("WebDriverを終了します。")
        close_driver()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Twitter自動返信システムのメインコントローラー")
    parser.add_argument(
        "--timestamp",
        type=str,
        default=None,
        help="出力ファイル名に使用するタイムスタンプ（例: 20250711_161308）。指定しない場合は現在時刻で自動生成されます。"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=None,
        help=f"収集するリプライの期間を時間で指定します。指定しない場合はconfig.pyの値({HOURS_TO_COLLECT}時間)が使われます。"
    )
    parser.add_argument(
        "--live-run",
        action='store_true',
        help="このフラグを立てると、実際に投稿やいいねを行います（ドライランを無効化）。"
    )
    parser.add_argument(
        "--headless",
        action='store_true',
        help="このフラグを立てると、ブラウザをヘッドレスモード（非表示）で起動します。"
    )
    args = parser.parse_args()

    main(timestamp_str=args.timestamp, hours_arg=args.hours, live_run=args.live_run, headless=args.headless)