import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / 'replies.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
      CREATE TABLE IF NOT EXISTS replied (
        tweet_id       TEXT PRIMARY KEY,
        user_id        TEXT,
        reply_text     TEXT,
        is_my_thread   BOOLEAN DEFAULT FALSE,
        timestamp      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    ''')
    conn.execute('''
      CREATE TABLE IF NOT EXISTS user_preferences (
        user_id      TEXT PRIMARY KEY,
        nickname     TEXT,
        language     TEXT,
        basic_response TEXT
      )
    ''')
    conn.commit()
    conn.close()

def is_replied(tweet_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    exists = conn.execute(
        'SELECT 1 FROM replied WHERE tweet_id = ?', (tweet_id,)
    ).fetchone() is not None
    conn.close()
    return exists

def mark_replied(tweet_id: str, user_id: str, reply_text: str, is_my_thread: bool = False):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''
        INSERT OR IGNORE INTO replied(tweet_id, user_id, reply_text, is_my_thread, timestamp) 
        VALUES (?, ?, ?, ?, ?)
        ''', (tweet_id, user_id, reply_text, is_my_thread, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_thread_info(tweet_id: str):
    """スレッド情報を取得"""
    conn = sqlite3.connect(DB_PATH)
    result = conn.execute(
        'SELECT is_my_thread FROM replied WHERE tweet_id = ?', (tweet_id,)
    ).fetchone()
    conn.close()
    return result[0] if result else None

def purge_old(hours: int = 24):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
      "DELETE FROM replied WHERE timestamp < datetime('now', '-{} hours')".format(hours)
    )
    conn.commit()
    conn.close()

def add_user_preference(user_id: str, nickname: str, language: str, basic_response: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''
        INSERT OR REPLACE INTO user_preferences (user_id, nickname, language, basic_response)
        VALUES (?, ?, ?, ?)
        ''', (user_id, nickname, language, basic_response)
    )
    conn.commit()
    conn.close()

def get_user_preference(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    preference = conn.execute(
        'SELECT nickname, language, basic_response FROM user_preferences WHERE user_id = ?', (user_id,)
    ).fetchone()
    conn.close()
    return preference 