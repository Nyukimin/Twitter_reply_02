"""
統合された返信判定システム
複数の判定方法を組み合わせた堅牢な返信検出アルゴリズム
"""

import logging
import re
from typing import Dict, List, Tuple, Optional
from bs4 import BeautifulSoup
from .thread_analysis_fix import _get_complete_thread_improved

# 返信判定専用ログ
unified_logger = logging.getLogger('unified_reply_detection')
handler = logging.FileHandler('log/unified_reply_detection.log', encoding='utf-8')
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
unified_logger.addHandler(handler)
unified_logger.setLevel(logging.DEBUG)

class ReplyDetectionEngine:
    """
    統合返信判定エンジン
    複数の判定方法を組み合わせて信頼性の高い返信検出を実現
    """
    
    def __init__(self):
        self.detection_methods = [
            self._method_text_patterns,
            self._method_aria_labels, 
            self._method_dom_structure,
            self._method_url_analysis,
            self._method_visual_hierarchy,
            self._method_contextual_analysis,
            self._method_csv_data_correlation
        ]
        
        # 各判定方法の重み（信頼度に基づく）
        self.method_weights = {
            'text_patterns': 0.25,      # テキストパターン
            'aria_labels': 0.20,        # aria-label属性
            'dom_structure': 0.15,      # DOM構造
            'url_analysis': 0.10,       # URL解析
            'visual_hierarchy': 0.10,   # 視覚的階層
            'contextual_analysis': 0.15, # 文脈解析
            'csv_data_correlation': 0.05 # CSVデータ照合
        }
    
    def detect_reply_comprehensive(self, article: BeautifulSoup, tweet_id: str = None, 
                                 csv_data: Dict = None) -> Tuple[bool, float, Dict]:
        """
        包括的な返信判定
        
        Returns:
            Tuple[bool, float, Dict]: (判定結果, 信頼度スコア, 詳細情報)
        """
        unified_logger.info(f"=== 統合返信判定開始: ID={tweet_id} ===")
        
        results = {}
        total_score = 0.0
        
        # 各判定方法を実行
        for method in self.detection_methods:
            method_name = method.__name__.replace('_method_', '')
            try:
                is_reply, confidence, details = method(article, csv_data)
                weight = self.method_weights.get(method_name, 0.1)
                weighted_score = confidence * weight if is_reply else 0.0
                
                results[method_name] = {
                    'is_reply': is_reply,
                    'confidence': confidence,
                    'details': details,
                    'weight': weight,
                    'weighted_score': weighted_score
                }
                
                total_score += weighted_score
                
                unified_logger.debug(f"方法 '{method_name}': {is_reply}, 信頼度={confidence:.2f}, 重み付きスコア={weighted_score:.3f}")
                
            except Exception as e:
                unified_logger.error(f"判定方法 '{method_name}' でエラー: {e}")
                results[method_name] = {
                    'is_reply': False,
                    'confidence': 0.0,
                    'details': f"エラー: {str(e)}",
                    'weight': 0.0,
                    'weighted_score': 0.0
                }
        
        # 総合判定（スコアが0.3以上で返信と判定）
        final_decision = total_score >= 0.3
        
        # 追加の一致性チェック
        positive_methods = sum(1 for r in results.values() if r['is_reply'])
        consistency_bonus = 0.1 if positive_methods >= 3 else 0.0
        final_score = min(total_score + consistency_bonus, 1.0)
        
        unified_logger.info(f"統合判定結果: {final_decision}, 最終スコア={final_score:.3f}, 陽性方法数={positive_methods}")
        
        return final_decision, final_score, results
    
    def _method_text_patterns(self, article: BeautifulSoup, csv_data: Dict = None) -> Tuple[bool, float, str]:
        """方法1: 改善されたテキストパターン検索"""
        patterns = [
            (r'Replying to', 0.9),      # 英語（高信頼度）
            (r'返信先[：:]', 0.9),       # 日本語（高信頼度）
            (r'En respuesta a', 0.85),  # スペイン語
            (r'Répondre à', 0.85),      # フランス語
            (r'In reply to', 0.8),      # 英語バリエーション
            (r'Reply to', 0.75),        # 英語短縮形
            (r'Re:', 0.6),              # 短縮形（低信頼度）
            (r'@\w+.*返信', 0.7),       # 日本語＋メンション
            (r'@\w+.*reply', 0.7),      # 英語＋メンション
        ]
        
        all_text = article.get_text()
        
        for pattern, confidence in patterns:
            if re.search(pattern, all_text, re.IGNORECASE):
                return True, confidence, f"パターン '{pattern}' で検出"
        
        return False, 0.0, "テキストパターンなし"
    
    def _method_aria_labels(self, article: BeautifulSoup, csv_data: Dict = None) -> Tuple[bool, float, str]:
        """方法2: aria-label属性による判定"""
        selectors = [
            ('[aria-label*="Replying to"]', 0.9),
            ('[aria-label*="返信先"]', 0.9),
            ('[aria-label*="En respuesta a"]', 0.85),
            ('[aria-label*="Répondre à"]', 0.85),
            ('[data-testid="inReplyTo"]', 0.8),
            ('[aria-labelledby*="reply"]', 0.7),
        ]
        
        for selector, confidence in selectors:
            elements = article.select(selector)
            if elements:
                # 返信ボタン自体は除外
                for elem in elements:
                    elem_text = elem.get_text().strip()
                    aria_label = elem.get('aria-label', '')
                    
                    # 返信先表示かどうかを確認
                    if ('button' in selector.lower() and 
                        not any(keyword in (elem_text + aria_label).lower() 
                               for keyword in ['to', '先', '返信先', 'respuesta', 'répondre'])):
                        continue
                    
                    return True, confidence, f"セレクタ '{selector}' で検出"
        
        return False, 0.0, "aria-label属性なし"
    
    def _method_dom_structure(self, article: BeautifulSoup, csv_data: Dict = None) -> Tuple[bool, float, str]:
        """方法3: DOM構造による判定"""
        # ツイート本文要素を特定
        tweet_text_div = (article.find('div', {'data-testid': 'tweetText'}) or 
                          article.find('div', {'data-testid': 'tweetContent'}) or
                          article.find('[data-testid*="text"]'))
        
        reply_keywords = ['replying', '返信', 'respuesta', 'répondre', 'antwort', '回复', '답글', 'reply to', 'in reply']
        
        # 構造的な返信先検出
        for elem in article.find_all(['span', 'div', 'a']):
            elem_text = elem.get_text().strip()
            if not elem_text:
                continue
                
            # ツイート本文内の@メンションは除外
            if tweet_text_div and elem in tweet_text_div.descendants:
                continue
                
            # @メンションと返信キーワードの組み合わせ
            has_mention = re.search(r'@\w+', elem_text)
            has_reply_keyword = any(keyword in elem_text.lower() for keyword in reply_keywords)
            
            if has_mention and has_reply_keyword:
                confidence = 0.8 if len(elem_text) < 100 else 0.6  # 短いテキストほど信頼度高
                return True, confidence, f"DOM構造で検出: '{elem_text[:50]}...'"
        
        return False, 0.0, "DOM構造パターンなし"
    
    def _method_url_analysis(self, article: BeautifulSoup, csv_data: Dict = None) -> Tuple[bool, float, str]:
        """方法4: URL解析による判定"""
        url_patterns = [
            (r'in_reply_to', 0.9),      # URLパラメータ（高信頼度）
            (r'reply_to', 0.85),        # reply_toパラメータ
            (r'/status/.*reply', 0.7),  # ステータスURLでreply含有
            (r'conversation_id', 0.6),  # 会話ID（低信頼度）
        ]
        
        links = article.find_all('a', href=True)
        
        for link in links:
            href = link['href']
            for pattern, confidence in url_patterns:
                if re.search(pattern, href, re.IGNORECASE):
                    return True, confidence, f"URLパターン '{pattern}' で検出: {href[:50]}..."
        
        return False, 0.0, "URL パターンなし"
    
    def _method_visual_hierarchy(self, article: BeautifulSoup, csv_data: Dict = None) -> Tuple[bool, float, str]:
        """方法5: 視覚的階層による判定"""
        # インデント・マージンによる返信階層の検出
        style_attr = article.get('style', '')
        parent_styles = []
        
        current = article.parent
        for _ in range(3):  # 親要素3階層まで確認
            if current and hasattr(current, 'get'):
                parent_style = current.get('style', '')
                if parent_style:
                    parent_styles.append(parent_style)
                current = current.parent
            else:
                break
        
        all_styles = [style_attr] + parent_styles
        
        for style in all_styles:
            # padding-left, margin-leftの値で階層判定
            padding_match = re.search(r'padding-left:\s*(\d+)', style)
            margin_match = re.search(r'margin-left:\s*(\d+)', style)
            
            if padding_match:
                padding_val = int(padding_match.group(1))
                if padding_val > 20:
                    confidence = min(0.8, padding_val / 100)  # パディング値に比例
                    return True, confidence, f"階層構造（padding: {padding_val}px）で検出"
                    
            if margin_match:
                margin_val = int(margin_match.group(1))
                if margin_val > 20:
                    confidence = min(0.8, margin_val / 100)  # マージン値に比例
                    return True, confidence, f"階層構造（margin: {margin_val}px）で検出"
        
        return False, 0.0, "視覚的階層なし"
    
    def _method_contextual_analysis(self, article: BeautifulSoup, csv_data: Dict = None) -> Tuple[bool, float, str]:
        """方法6: 文脈解析による判定"""
        all_text = article.get_text()
        
        # @メンションの出現パターン分析
        mentions = re.findall(r'@(\w+)', all_text)
        if not mentions:
            return False, 0.0, "@メンションなし"
        
        # 作者情報の取得
        author = self._get_author_from_article(article)
        author_without_at = author.lstrip('@') if author else ""
        
        # 他ユーザーへの@メンション
        other_mentions = [m for m in mentions if m != author_without_at]
        
        if other_mentions:
            # ツイート冒頭での@メンション（返信パターン）
            first_50_chars = all_text[:50]
            early_mentions = [m for m in other_mentions if f'@{m}' in first_50_chars]
            
            if early_mentions:
                # メンション数による信頼度調整
                mention_count = len(other_mentions)
                if mention_count == 1:
                    confidence = 0.8  # 単一メンション（典型的な返信）
                elif mention_count <= 3:
                    confidence = 0.6  # 複数メンション（会話）
                else:
                    confidence = 0.4  # 多数メンション（低信頼度）
                
                return True, confidence, f"文脈解析: 冒頭@メンション {early_mentions}"
        
        return False, 0.0, "文脈パターンなし"
    
    def _method_csv_data_correlation(self, article: BeautifulSoup, csv_data: Dict = None) -> Tuple[bool, float, str]:
        """方法7: CSVデータとの照合判定"""
        if not csv_data:
            return False, 0.0, "CSVデータなし"
        
        # CSVのreply_to フィールドをチェック
        reply_to = csv_data.get('reply_to', '')
        if reply_to and reply_to != csv_data.get('UserID', ''):
            return True, 0.7, f"CSVデータで返信先確認: {reply_to}"
        
        # 特殊属性の確認
        special_attrs = ['data-tweet-depth', 'data-reply-level', 'data-conversation-id']
        for attr in special_attrs:
            if article.get(attr):
                return True, 0.6, f"特殊属性 '{attr}' で検出"
        
        return False, 0.0, "CSVデータ照合なし"
    
    def _get_author_from_article(self, article: BeautifulSoup) -> Optional[str]:
        """記事要素から投稿者のユーザーIDを取得"""
        user_name_div = article.find('div', {'data-testid': 'User-Name'})
        if user_name_div:
            user_link = user_name_div.find('a', {'role': 'link', 'href': lambda href: href and href.startswith('/') and '/status/' not in href})
            if user_link and 'href' in user_link.attrs:
                return user_link['href'].lstrip('/')
        return None

# 統合判定エンジンのインスタンス
reply_engine = ReplyDetectionEngine()

def detect_reply_unified(article: BeautifulSoup, tweet_id: str = None, csv_data: Dict = None) -> bool:
    """
    統合返信判定の主要エントリーポイント
    
    Args:
        article: BeautifulSoup article要素
        tweet_id: ツイートID（オプション）
        csv_data: CSVデータ（オプション）
    
    Returns:
        bool: 返信かどうかの判定結果
    """
    is_reply, confidence, details = reply_engine.detect_reply_comprehensive(article, tweet_id, csv_data)
    
    # 詳細ログの出力
    unified_logger.info(f"最終判定: {is_reply} (信頼度: {confidence:.3f})")
    for method_name, result in details.items():
        unified_logger.debug(f"  {method_name}: {result['is_reply']} ({result['confidence']:.2f})")
    
    return is_reply