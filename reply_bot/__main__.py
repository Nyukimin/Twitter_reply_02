#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
reply_botモジュールのエントリーポイント

python -m reply_bot.check_login_status で実行できるようにするための__main__.py
"""

import sys
import argparse

def main():
    """メインエントリーポイント"""
    # コマンドライン引数を解析
    # `python -m reply_bot.check_login_status` と `python -m reply_bot check_login_status` の両方をサポート
    if len(sys.argv) > 1:
        if sys.argv[1] == 'check_login_status':
            # サブコマンド形式の場合
            from .check_login_status import main as check_login_main
            sys.argv = [sys.argv[0]] + sys.argv[2:]  # サブコマンドを削除
            check_login_main()
        elif sys.argv[1] == 'simple_test':
            # simple_testサブコマンド
            from .simple_test import main as simple_test_main
            sys.argv = [sys.argv[0]] + sys.argv[2:]  # サブコマンドを削除
            simple_test_main()
        else:
            print(f"不明なコマンド: {sys.argv[1]}")
            print_help()
            sys.exit(1)
    elif '.' in sys.argv[0] and 'check_login_status' in sys.argv[0]:
        # 直接モジュール指定形式の場合 (python -m reply_bot.check_login_status)
        from .check_login_status import main as check_login_main
        check_login_main()
    elif '.' in sys.argv[0] and 'simple_test' in sys.argv[0]:
        # 直接モジュール指定形式の場合 (python -m reply_bot.simple_test)
        from .simple_test import main as simple_test_main
        simple_test_main()
    else:
        # ヘルプを表示
        print_help()
        sys.exit(1)

def print_help():
    """ヘルプメッセージを表示"""
    print("使用方法:")
    print("  python -m reply_bot.check_login_status [--headless]")
    print("  python -m reply_bot check_login_status [--headless]")
    print("  python -m reply_bot.simple_test [--message 'メッセージ']")
    print("  python -m reply_bot simple_test [--message 'メッセージ']")
    print("")
    print("利用可能なコマンド:")
    print("  check_login_status - Twitterのログイン状態を確認します")
    print("  simple_test        - モジュール実行のテスト")
    print("")
    print("オプション:")
    print("  --headless - ブラウザをヘッドレスモード（非表示）で起動します")
    print("  --message  - テストメッセージを指定します")

if __name__ == "__main__":
    main()
