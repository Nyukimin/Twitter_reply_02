import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / 'replies.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
      CREATE TABLE IF NOT EXISTS replied (
        reply_id   TEXT PRIMARY KEY,
        replied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

def is_replied(reply_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    exists = conn.execute(
        'SELECT 1 FROM replied WHERE reply_id = ?', (reply_id,)
    ).fetchone() is not None
    conn.close()
    return exists

def mark_replied(reply_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'INSERT OR IGNORE INTO replied(reply_id) VALUES (?)', (reply_id,)
    )
    conn.commit()
    conn.close()

def purge_old(hours: int = 24):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
      "DELETE FROM replied WHERE replied_at < datetime('now', '-{} hours')".format(hours)
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