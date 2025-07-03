import asyncio
import logging
import time
from playwright.async_api import Playwright, async_playwright, expect
from .config import LOGIN_URL, USERNAME, PASSWORD

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def post_reply(tweet_id: str, reply_id: str, reply_text: str):
    """
    Playwrightを使用してXにログインし、指定されたリプライを投稿します。
    
    Args:
        tweet_id (str): 返信元のツイートID。
        reply_id (str): リプライ自身のID。
        reply_text (str): 投稿する返信の本文。
    """
    logging.info(f"リプライ投稿を開始します。返信元ツイートID: {tweet_id}, リプライID: {reply_id}")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True) # ヘッドレスモードでブラウザを起動
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # ログインURLへ移動
            logging.info(f"ログインページへ移動中: {LOGIN_URL}")
            await page.goto(LOGIN_URL)

            # ログイン処理
            # ユーザー名入力フィールドの特定と入力
            await page.locator('input[name="text"]').fill(USERNAME)
            await page.locator('button:has-text("次へ")').click()

            # パスワード入力フィールドの特定と入力
            # パスワードフィールドのセレクタは動的に変わる可能性があるため、注意が必要
            await page.locator('input[name="password"]').fill(PASSWORD)
            await page.locator('button:has-text("ログイン")').click()

            # ログイン成功の確認 (例: ホーム画面の特定の要素が表示されるまで待つ)
            await page.wait_for_url("https://x.com/home") # または、アカウントのプロフィールURLなど
            logging.info("ログイン成功！")

            # 対象ツイートのリプライ画面へ移動
            tweet_url = f"https://x.com/any_user/status/{tweet_id}" # any_userはダミー。実際にはtweet_idからユーザー名を特定する必要がある場合も
            logging.info(f"対象ツイートのリプライ画面へ移動中: {tweet_url}")
            await page.goto(tweet_url)
            
            # リプライボックスが表示されるまで待機
            await page.locator('div[data-testid="replyButton"]').wait_for()

            # リプライの入力と投稿
            logging.info(f"リプライを投稿中: {reply_text[:50]}...")
            await page.locator('div[data-testid="replyInput"]').fill(reply_text)
            await page.locator('button[data-testid="tweetButton"]').click()

            # 投稿成功の確認 (例: 投稿がリストに追加される、または成功メッセージが表示されるまで待つ)
            # ここでは簡易的に数秒待機
            await asyncio.sleep(5) # 投稿処理が完了するのを待つ
            logging.info("リプライ投稿完了！")

        except Exception as e:
            logging.error(f"リプライ投稿中にエラーが発生しました: {e}")
            # エラー発生時のスクリーンショットを保存 (デバッグ用)
            await page.screenshot(path=f"error_screenshot_{time.time()}.png")
        finally:
            await browser.close()

async def post(tweet_id: str, reply_id: str, reply_text: str):
    """
    post_replyのラッパー関数。非同期処理の実行を管理します。
    """
    await post_reply(tweet_id, reply_id, reply_text)
    # 複数回投稿の際に間隔を置くための処理は main.py で制御します。


if __name__ == "__main__":
    # テスト用のダミーデータ
    test_tweet_id = "1460323737035677700" # 実際の有効なツイートIDに置き換えてください
    test_reply_id = "1460323737035677701" # ダミーID
    test_reply_content = "テスト返信です。" # OpenAIで生成される内容に置き換える

    print(f"テストとしてリプライを投稿します。ツイートID: {test_tweet_id}, 内容: {test_reply_content}")
    asyncio.run(post(test_tweet_id, test_reply_id, test_reply_content)) 