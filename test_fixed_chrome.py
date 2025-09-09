#!/usr/bin/env python3
"""
fixed_chromeの動作テスト用スクリプト
"""

import sys
import os
import logging
from pathlib import Path

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_fixed_chrome():
    """fixed_chromeの設定をテスト"""
    try:
        logger.info("=== fixed_chrome動作テスト開始 ===")
        
        # パス確認
        fixed_chrome_dir = Path("fixed_chrome")
        chromedriver_path = fixed_chrome_dir / "chromedriver" / "chromedriver-win64" / "chromedriver.exe"
        chrome_path = fixed_chrome_dir / "chrome" / "chrome-win64" / "chrome.exe"
        
        logger.info(f"ChromeDriver確認: {chromedriver_path}")
        logger.info(f"Chrome確認: {chrome_path}")
        
        if not chromedriver_path.exists():
            logger.error(f"ChromeDriverが見つかりません: {chromedriver_path}")
            return False
            
        if not chrome_path.exists():
            logger.error(f"Chrome実行ファイルが見つかりません: {chrome_path}")
            return False
            
        logger.info("✅ ファイル存在確認: OK")
        
        # Chrome Profile Managerのテスト
        logger.info("Chrome Profile Managerをテスト中...")
        
        sys.path.append(str(Path("shared_modules/chrome_profile_manager")))
        from chrome_profile_manager import ProfiledChromeManager
        
        # プロファイルマネージャーの初期化
        manager = ProfiledChromeManager("./profiles")
        
        # fixed_chromeパスが正しく設定されているか確認
        if hasattr(manager, 'fixed_chrome_dir'):
            logger.info(f"✅ fixed_chrome_dir設定: {manager.fixed_chrome_dir}")
        else:
            logger.error("❌ fixed_chrome_dir設定なし")
            return False
            
        logger.info("=== fixed_chrome動作テスト完了 ===")
        return True
        
    except Exception as e:
        logger.error(f"テスト中にエラー: {e}")
        return False

if __name__ == "__main__":
    success = test_fixed_chrome()
    if success:
        logger.info("🎉 テスト成功: fixed_chromeの設定が完了しました")
        sys.exit(0)
    else:
        logger.error("❌ テスト失敗: 設定に問題があります")
        sys.exit(1)