"""
WebDriverの安定性を向上させるためのヘルパーモジュール
メモリリークやクラッシュからの自動回復機能を提供
"""

import logging
import time
import traceback
from typing import Callable, Any, Optional
from selenium import webdriver
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException
from .utils import force_restart_driver, check_memory_usage

class WebDriverStabilizer:
    """
    WebDriverの安定性を向上させるためのラッパークラス
    """
    
    def __init__(self, driver: webdriver.Chrome, max_retries: int = 3, memory_threshold: float = 600.0, headless: bool = False):
        self.driver = driver
        self.max_retries = max_retries
        self.memory_threshold = memory_threshold  # MB
        self.headless = headless
        self.error_count = 0
        self.last_restart_time = 0
        self.min_restart_interval = 300  # 5分間隔で再起動制限
        
    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """
        指定された関数をWebDriverエラーに対する再試行機能付きで実行
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                # メモリ使用量をチェック
                memory_mb = check_memory_usage()
                if memory_mb and memory_mb > self.memory_threshold:
                    logging.warning(f"メモリ使用量が閾値を超えています: {memory_mb:.1f} MB > {self.memory_threshold} MB")
                    self._restart_driver_if_needed()
                
                # 関数を実行
                result = func(*args, **kwargs)
                
                # 成功時はエラーカウントをリセット
                self.error_count = 0
                return result
                
            except WebDriverException as e:
                self.error_count += 1
                last_exception = e
                logging.warning(f"WebDriverエラー発生 (試行 {attempt + 1}/{self.max_retries}): {e}")
                
                # 特定のエラーの場合は即座に再起動
                if self._should_restart_immediately(e):
                    logging.warning("重大なWebDriverエラーを検出。即座に再起動します。")
                    self._restart_driver_if_needed()
                
                # 最後の試行でない場合は少し待機
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数バックオフ
                    
            except Exception as e:
                self.error_count += 1
                last_exception = e
                logging.error(f"予期しないエラー発生 (試行 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # 全ての試行が失敗した場合
        logging.error(f"最大試行回数 {self.max_retries} に達しました。最後のエラー: {last_exception}")
        raise last_exception
    
    def _should_restart_immediately(self, exception: Exception) -> bool:
        """
        例外の内容に基づいて即座に再起動すべきかを判定
        """
        error_message = str(exception).lower()
        
        # Chrome/WebDriverのクラッシュを示すパターン
        crash_patterns = [
            'chrome not reachable',
            'session not created',
            'no such session',
            'chrome failed to start',
            'gethandleverifier',
            'basethreadinitthunk',
            'rtlinitializeexceptionchain',
            'chrome crashed',
            'session deleted because of page crash'
        ]
        
        return any(pattern in error_message for pattern in crash_patterns)
    
    def _restart_driver_if_needed(self):
        """
        必要に応じてWebDriverを再起動
        """
        current_time = time.time()
        
        # 最小間隔チェック
        if current_time - self.last_restart_time < self.min_restart_interval:
            logging.info(f"再起動の最小間隔({self.min_restart_interval}秒)内のため、再起動をスキップします。")
            return
        
        # エラー数が閾値を超えた場合も再起動
        if self.error_count >= 3:
            logging.warning(f"エラー数が閾値を超えました（{self.error_count}回）。WebDriverを再起動します。")
        
        try:
            self.driver = force_restart_driver(headless=self.headless)
            self.last_restart_time = current_time
            self.error_count = 0
            logging.info("WebDriverの再起動が完了しました。")
        except Exception as e:
            logging.error(f"WebDriverの再起動中にエラー: {e}")
            raise e

def safe_execute(driver: webdriver.Chrome, func: Callable, headless: bool = False, *args, **kwargs) -> Any:
    """
    WebDriverStabilizerを使用して関数を安全に実行するヘルパー関数
    """
    stabilizer = WebDriverStabilizer(driver, headless=headless)
    return stabilizer.execute_with_retry(func, *args, **kwargs)

def handle_webdriver_error(func: Callable) -> Callable:
    """
    WebDriverエラーハンドリングのデコレータ
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WebDriverException as e:
            error_context = {
                'function': func.__name__,
                'args': str(args)[:100],  # 長すぎる場合は切り詰め
                'error': str(e),
                'traceback': traceback.format_exc()
            }
            logging.error(f"WebDriverエラーが発生しました: {error_context}")
            raise e
        except Exception as e:
            error_context = {
                'function': func.__name__,
                'args': str(args)[:100],
                'error': str(e),
                'traceback': traceback.format_exc()
            }
            logging.error(f"予期しないエラーが発生しました: {error_context}")
            raise e
    
    return wrapper