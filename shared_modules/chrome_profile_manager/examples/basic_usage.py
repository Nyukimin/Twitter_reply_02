"""Chrome Profile Manager の基本的な使用例"""

from chrome_profile_manager import ProfiledChromeManager
import time

def basic_example():
    """基本的な使用例"""
    # マネージャー初期化
    manager = ProfiledChromeManager(base_profiles_dir="./test_profiles")
    
    print("=== Chrome Profile Manager - 基本使用例 ===")
    
    # 新規プロファイル作成 + Chrome起動
    print("1. 新規プロファイル作成 + Chrome起動")
    driver = manager.create_and_launch(
        profile_name="test_profile",
        window_size=(1200, 800),
        headless=False
    )
    
    # 基本的な操作
    print("2. Webページへのアクセス")
    driver.get("https://example.com")
    print(f"現在のURL: {driver.current_url}")
    print(f"ページタイトル: {driver.title}")
    
    # 少し待機
    time.sleep(3)
    
    # 終了
    driver.quit()
    print("3. ブラウザ終了")
    
    # 既存プロファイルで再起動
    print("4. 既存プロファイルで再起動")
    driver = manager.launch_existing("test_profile")
    driver.get("https://httpbin.org/user-agent")
    time.sleep(2)
    driver.quit()
    
    # プロファイル管理
    print("5. プロファイル管理")
    profiles = manager.list_profiles()
    print(f"利用可能なプロファイル: {profiles}")
    
    # バックアップ作成
    backup_path = manager.backup_profile("test_profile")
    print(f"バックアップ作成: {backup_path}")
    
    print("=== 完了 ===")

def custom_options_example():
    """カスタムオプション使用例"""
    manager = ProfiledChromeManager()
    
    print("=== カスタムオプション使用例 ===")
    
    # 高度な設定でChrome起動
    driver = manager.create_and_launch(
        profile_name="custom_profile",
        headless=True,                          # ヘッドレスモード
        window_size=(1920, 1080),               # ウィンドウサイズ
        user_agent="Custom Bot UserAgent",      # カスタムUserAgent
        disable_images=True,                    # 画像読み込み無効
        # proxy="socks5://127.0.0.1:1080",     # プロキシ（コメントアウト）
    )
    
    # User-Agent確認
    driver.get("https://httpbin.org/user-agent")
    print("User-Agent確認ページにアクセス完了")
    
    driver.quit()
    print("=== カスタムオプション例完了 ===")

if __name__ == "__main__":
    try:
        basic_example()
        print("\n" + "="*50 + "\n")
        custom_options_example()
    except Exception as e:
        print(f"エラーが発生しました: {e}")