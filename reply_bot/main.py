import logging
import os
from datetime import datetime

# 各モジュールのメイン処理関数をインポート
from .csv_generator import main_process as csv_generator_main
from .reply_processor import main_process as reply_processor_main
from .post_reply import main_process as post_reply_main
from .config import HOURS_TO_COLLECT
from .utils import setup_driver, close_driver

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    """
    自動返信システムのメイン処理フローを制御します。
    """
    logging.info("=== 自動返信システムを開始します ===")
    
    driver = None
    try:
        # 最初にWebDriverを一度だけセットアップ
        driver = setup_driver(headless=False)
        if not driver:
            logging.error("WebDriverの初期化に失敗しました。処理を中断します。")
            return

        # --------------------------------------------------------------------------
        # ステップ1: 通知ページからリプライを取得し、CSVを生成
        # --------------------------------------------------------------------------
        logging.info("--- [ステップ1/3] リプライの取得とCSV生成を開始します ---")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        initial_csv_path_template = os.path.join('output', f'extracted_tweets_{timestamp}.csv')
        
        initial_csv_path = csv_generator_main(
            driver=driver,
            output_csv_path=initial_csv_path_template, 
            hours_to_collect=HOURS_TO_COLLECT
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
        # ここでは常にドライランで実行する。ライブ実行は手動を想定。
        post_reply_main(driver, processed_csv_path, dry_run=True)
        
        logging.info("=== 全ての処理が正常に完了しました ===")
    
    except Exception as e:
        logging.error(f"メイン処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        # 全ての処理が終了したら、WebDriverを閉じる
        logging.info("WebDriverを終了します。")
        close_driver()


if __name__ == "__main__":
    main() 