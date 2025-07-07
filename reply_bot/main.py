import logging
import os
from datetime import datetime

# 各モジュールのメイン処理関数をインポート
from .csv_generator import main_process as csv_generator_main
from .thread_checker import main_process as thread_checker_main
from .gen_reply import main_process as gen_reply_main
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
        # ユーザーの記憶に基づき、デバッグ中はFalseを維持 [[memory:2213753]]
        driver = setup_driver(headless=False)
        if not driver:
            logging.error("WebDriverの初期化に失敗しました。処理を中断します。")
            return

        # --------------------------------------------------------------------------
        # ステップ1: 通知ページからリプライを取得し、CSVを生成
        # --------------------------------------------------------------------------
        logging.info("--- [ステップ1/4] リプライの取得とCSV生成を開始します ---")
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
        # ステップ2: スレッドの起点が自分か判定
        # --------------------------------------------------------------------------
        logging.info("--- [ステップ2/4] スレッド起点の判定を開始します ---")
        rechecked_csv_path = thread_checker_main(driver, initial_csv_path)
        
        if not rechecked_csv_path or not os.path.exists(rechecked_csv_path):
            logging.warning("ステップ2で判定済みCSVファイルが生成されませんでした。後続処理をスキップします。")
            logging.info("=== 自動返信システムを終了します ===")
            return
        logging.info(f"スレッド起点の判定結果を {rechecked_csv_path} に保存しました。")
            

        # --------------------------------------------------------------------------
        # ステップ3: AIによる返信文の生成 (このステップはWebDriverを必要としない)
        # --------------------------------------------------------------------------
        logging.info("--- [ステップ3/4] AIによる返信文の生成を開始します ---")
        generated_csv_path = gen_reply_main(rechecked_csv_path)

        if not generated_csv_path or not os.path.exists(generated_csv_path):
            logging.warning("ステップ3で返信生成済みCSVファイルが見つかりませんでした。後続処理をスキップします。")
            logging.info("=== 自動返信システムを終了します ===")
            return
        logging.info(f"AIによる返信文を {generated_csv_path} に保存しました。")


        # --------------------------------------------------------------------------
        # ステップ4: いいね＆返信投稿 (デフォルトはドライラン)
        # --------------------------------------------------------------------------
        logging.info("--- [ステップ4/4] いいねと返信の投稿処理を開始します ---")
        # ここでは常にドライランで実行する。ライブ実行は手動を想定。
        post_reply_main(driver, generated_csv_path, dry_run=True)
        
        logging.info("=== 全ての処理が正常に完了しました ===")
    
    except Exception as e:
        logging.error(f"メイン処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
    finally:
        # 全ての処理が終了したら、WebDriverを閉じる
        logging.info("WebDriverを終了します。")
        close_driver()


if __name__ == "__main__":
    main() 