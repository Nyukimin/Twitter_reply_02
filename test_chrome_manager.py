from shared_modules.chrome_profile_manager.chrome_profile_manager.manager import ProfiledChromeManager
import logging

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_chrome_manager():
    print("=== Chrome Profile Manager テスト開始 ===")
    
    # マネージャーを初期化
    manager = ProfiledChromeManager()
    
    # 一時プロファイルクリーンアップをテスト
    print("\n=== 一時プロファイルクリーンアップテスト ===")
    deleted_count = manager.cleanup_temp_profiles(older_than_hours=0.1)  # 6分前より古い
    print(f"削除されたプロファイル数: {deleted_count}")
    
    # 実行中のChromeプロセス情報を取得
    print("\n=== 実行中のChromeプロセス ===")
    chrome_procs = manager.get_running_chrome_processes()
    if chrome_procs:
        for proc in chrome_procs:
            print(f"PID: {proc['pid']}, Name: {proc['name']}, Memory: {proc['memory_mb']}MB")
    else:
        print("実行中のChromeプロセスが見つかりません")
    
    # プロファイル一覧を表示
    print("\n=== 利用可能なプロファイル ===")
    profiles = manager.list_profiles()
    for profile in profiles:
        print(f"プロファイル: {profile}")
    
    print("\n=== テスト完了 ===")

if __name__ == "__main__":
    test_chrome_manager()