"""
返信判定機能のテストスクリプト
改善された返信判定ロジックの動作確認用
"""

import sys
import os
import pandas as pd
import logging
from bs4 import BeautifulSoup

# パスを追加してモジュールをインポート
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from reply_bot.reply_processor import _is_tweet_a_reply
from reply_bot.reply_detection_unified import detect_reply_unified

def test_reply_detection_on_csv(csv_file_path: str):
    """
    CSVファイルの実データを使用して返信判定機能をテスト
    """
    print(f"=== 返信判定テスト開始: {csv_file_path} ===")
    
    try:
        # CSVファイルを読み込み
        df = pd.read_csv(csv_file_path)
        print(f"読み込み完了: {len(df)}件のツイートデータ")
        
        # is_my_threadがTrueかつgenerated_replyが空のものを抽出（返信生成対象外になったもの）
        failed_replies = df[(df['is_my_thread'] == True) & (df['generated_reply'].isna() | (df['generated_reply'] == ''))]
        
        print(f"返信生成失敗件数: {len(failed_replies)}件 / {len(df)}件")
        print(f"失敗率: {len(failed_replies)/len(df)*100:.1f}%")
        
        if len(failed_replies) > 0:
            print("\n失敗したツイートのサンプル:")
            for i, (_, row) in enumerate(failed_replies.head(10).iterrows()):
                print(f"  {i+1}. ID: {row['reply_id']}, Author: {row['UserID']}")
                print(f"     Content: {row['contents'][:50]}...")
                print(f"     Lang: {row['lang']}")
        
        # 返信されているツイートの統計
        successful_replies = df[df['generated_reply'].notna() & (df['generated_reply'] != '')]
        print(f"\n返信生成成功件数: {len(successful_replies)}件")
        
        # 言語別の成功率
        lang_stats = df.groupby('lang').agg({
            'generated_reply': lambda x: (x.notna() & (x != '')).sum(),
            'reply_id': 'count'
        }).round(2)
        lang_stats['success_rate'] = (lang_stats['generated_reply'] / lang_stats['reply_id'] * 100).round(1)
        
        print("\n言語別成功率:")
        for lang, stats in lang_stats.iterrows():
            print(f"  {lang}: {stats['generated_reply']}/{stats['reply_id']} ({stats['success_rate']}%)")
        
        return len(failed_replies), len(df)
        
    except Exception as e:
        print(f"テストエラー: {e}")
        return None, None

def test_html_sources():
    """
    保存されたHTMLソースで返信判定をテスト
    """
    print("\n=== HTMLソース返信判定テスト ===")
    
    source_dir = "source"
    if not os.path.exists(source_dir):
        print("sourceディレクトリが見つかりません")
        return
    
    html_files = [f for f in os.listdir(source_dir) if f.endswith('.html')]
    print(f"HTMLファイル数: {len(html_files)}")
    
    # 最新のいくつかのファイルをテスト
    test_files = sorted(html_files)[-5:] if len(html_files) > 5 else html_files
    
    for html_file in test_files:
        print(f"\nテスト中: {html_file}")
        try:
            with open(os.path.join(source_dir, html_file), 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            soup = BeautifulSoup(html_content, 'html.parser')
            articles = soup.find_all('article', {'data-testid': 'tweet'})
            
            if not articles:
                articles = soup.select('[role="article"]')
            
            print(f"  見つかったarticle要素: {len(articles)}個")
            
            reply_count_old = 0
            reply_count_new = 0
            
            for i, article in enumerate(articles[:5]):  # 最初の5つをテスト
                # 従来の判定方法
                is_reply_old = _is_tweet_a_reply(article)
                
                # 新しい統合判定方法
                try:
                    is_reply_new = detect_reply_unified(article)
                except Exception as e:
                    print(f"    記事{i+1}: 統合判定エラー - {e}")
                    is_reply_new = False
                
                if is_reply_old:
                    reply_count_old += 1
                if is_reply_new:
                    reply_count_new += 1
                
                text = article.get_text()[:50] + "..." if len(article.get_text()) > 50 else article.get_text()
                print(f"    記事{i+1}: 従来={is_reply_old}, 新={is_reply_new} - {text}")
            
            print(f"  返信判定結果: 従来方法={reply_count_old}/{len(articles[:5])}, 新方法={reply_count_new}/{len(articles[:5])}")
            
        except Exception as e:
            print(f"  エラー: {e}")

def main():
    """メインテスト実行"""
    print("返信判定機能改善テスト")
    print("=" * 50)
    
    # 最新のCSVファイルでテスト
    output_dir = "output"
    if os.path.exists(output_dir):
        csv_files = [f for f in os.listdir(output_dir) if f.startswith('processed_replies_') and f.endswith('.csv')]
        if csv_files:
            latest_csv = sorted(csv_files)[-1]
            csv_path = os.path.join(output_dir, latest_csv)
            failed, total = test_reply_detection_on_csv(csv_path)
            
            if failed is not None:
                improvement_needed = failed > total * 0.15  # 15%以上失敗で改善要
                print(f"\n改善判定: {'要改善' if improvement_needed else '良好'}")
        else:
            print("processed_repliesのCSVファイルが見つかりません")
    
    # HTMLソースのテスト
    test_html_sources()
    
    print("\n=== テスト完了 ===")

if __name__ == "__main__":
    # ログレベルを設定してノイズを減らす
    logging.getLogger().setLevel(logging.WARNING)
    main()