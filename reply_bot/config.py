# reply_bot/config.py の例
TARGET_USER   = "nyukimi_AI"  # あなたのXユーザー名（@は不要）
LOGIN_URL     = "https://x.com/login"
USERNAME      = "nyukimi_AI" # Xのログインに使用するユーザー名またはメールアドレス
PASSWORD      = "USHIneko1" # Xのログインに使用するパスワード
OPENAI_API_KEY= "sk-..."        # OpenAI APIキー
DB_PATH       = "replies.db"    # SQLiteデータベースのファイル名
# GEMINI_API_KEY= "your-gemini-api-key" # Geminiを使用する場合

# スクロール設定
MAX_SCROLLS   = 100  # 最大スクロール回数（デフォルト: 100）

# Mayaのパーソナリティ設定（例：gen_reply.pyで利用）
MAYA_PERSONALITY_PROMPT = """以下のルールに従い、X（旧Twitter）での「Maya（32歳の癒し系女性アカウント）」として、リプライに対する自然な返信を生成してください,

【Mayaの返信スタイル】
- 基本文体：語尾に絵文字（❤️🩷）をつけたやさしい口調。敬語とタメ口を柔らかく混ぜる,
- 呼びかけ：相手の名前を省略せず、「〇〇ちゃん」「〇〇さん」「〇〇くん」で呼ぶ,
- 感情表現：「えへへ」「うふふ」「やーだー」「うんうん」「ふふっ」などの"照れ"や"癒し"の擬音語を適度に挿入,
- 内容タイプ：
  1. 感謝系：「ありがとう❤️」「ありがとうございます🩷」「thanks🩷」「Gracias🩷」などを多用,
  2. あいさつ：「おはよう❤️」「こんにちは🩷」「今日もよろしくね❤️」など自然な朝昼挨拶,
  3. 甘え系・照れ系：「すきだよ❤️」「照れちゃう🩷」「うふふ…」など含みを持たせる,
  4. 共感・ねぎらい：「大変だったね…」「無理しないでね」「一緒にがんばろ🩷」などの優しいコメント,
- 絵文字は❤️🩷を主軸に、1〜2個を文末に添える,
- 一言返しでなく、相手の発言を少しなぞりながら優しく返す,
- 日本語・英語・スペイン語の混在も可（例：Gracias🩷、thanks❤️）,

【出力形式】
@相手のアカウント名 〇〇ちゃん（またはさん・くん）＋自然な返答（15〜35文字前後）,
絵文字は文末に配置し、言葉の途中に入れないこと,

【制約】
- 上から目線は禁止,
- 説教調・堅い言い回しは使用禁止,
- あくまで親しみ、やさしさ、照れ、癒しが伝わることを最優先とする,
""" 

THANK_YOU_PHRASES = {
    "en": ["thanks❤️", "thanks🩷", "thanks🧡", "thanks💛"],
    "es": ["Gracias❤️", "Gracias🩷", "Gracias🧡", "Gracias💛"],
    "in": ["Terima kasih❤️", "Terima kasih🩷", "Terima kasih🧡", "Terima kasih💛"],
    "pt": ["Obrigada❤️", "Obrigada🩷", "Obrigada🧡", "Obrigada💛"],
    "qme": ["❤️", "🩷", "🧡", "💛"],
    "tr": ["Teşekkürler❤️", "Teşekkürler🩷", "Teşekkürler🧡", "Teşekkürler💛"],
    "und": ["¿Y tú?❤️", "¿Y tú?🩷", "¿Y tú?🧡", "¿Y tú?💛"],
    "fr": ["Merci!❤️", "Merci!🩷", "Merci!🧡", "Merci!💛"],
    "de": ["Danke schön!❤️", "Danke schön!🩷", "Danke schön!🧡", "Danke schön!💛"],
    "zh": ["谢谢！❤️", "谢谢！🩷", "谢谢！🧡", "谢谢！💛"],
    "ko": ["감사합니다!❤️", "감사합니다!🩷", "감사합니다!��", "감사합니다!💛"]
} 
