from reply_bot.db import init_db, add_user_preference

def add_preferences_to_db():
    init_db() # データベースが初期化されていることを確認

    preferences = [
        ("285smzgcsq36129", "七宝ちゃん", "ja", ""),
        ("2nd_karen_ai", "かれんちゃん", "ja", ""),
        ("48a03qlpaikzlwz", "すいくん", "ja", ""),
        ("ai8263353539674", "みうちゃん", "ja", ""),
        ("albijo_charm", "あやちゃん", "ja", ""),
        ("aichan_lovelyai", "あいちゃん", "ja", ""),
        ("aiidol_misaki", "みさきちゃん", "ja", ""),
        ("aisanmaru30", "さんまるちゃん", "ja", ""),
        ("akirachan_ai", "あきらちゃん", "ja", ""),
        ("aoi_cocona", "ここなちゃん", "ja", ""),
        ("disney_ikitasi", "ゆりちゃん", "ja", ""),
        ("erutea_ai37", "えるちゃん", "ja", ""),
        ("famous4771", "みかちゃん", "ja", ""),
        ("fancy_pop_pic", "ふぁぽちゃん", "ja", ""),
        ("frogblue1235951", "あおさん", "ja", ""),
        ("girl_ai001", "せなちゃん", "ja", ""),
        ("hinachan_ai", "ひなちゃん", "ja", ""),
        ("hisyoka_joshi", "秘書ちゃん", "ja", ""),
        ("honey_bee_610", "ハニちゃん", "ja", ""),
        ("ikayaki009", "ばいちゃん", "ja", ""),
        ("k2ewez2dzm2ltsu", "まさやん", "ja", ""),
        ("kasumi_haru66", "はるねちゃん", "ja", ""),
        ("kzn802", "はっちゃん", "ja", ""),
        ("lowleg_cotton", "ローレルちゃん", "ja", ""),
        ("manami_ofp", "まなみちゃん", "ja", ""),
        ("naginokobeya", "なぎちゃん", "ja", ""),
        ("natsu_natsuai", "なつちゃん", "ja", ""),
        ("nyukimi_ai", "すーちゃん", "ja", ""),
        ("reina_bb00", "れいなちゃん", "ja", ""),
        ("ren_ai0202", "れんちゃん", "ja", ""),
        ("rezaki75085", "るいちゃん", "ja", ""),
        ("rinaaltsweet", "みかちゃん", "ja", ""),
        ("saiyo_jp", "ゆなちゃん", "ja", ""),
        ("sakuaicute_girl2", "さくちゃん", "ja", ""),
        ("sakura_xsecret", "さくらちゃん", "ja", ""),
        ("seducerina", "りなちゃん", "ja", ""),
        ("sweet_momo_0415", "ももちゃん", "ja", ""),
        ("thuangyi8646", "土方さん", "ja", ""),
        ("tuyahimefukujyu", "ふくじゅちゃん", "ja", ""),
        ("yualovedays", "ゆあちゃん", "ja", ""),
        ("yv6lwzy7tb41253", "コネリちゃん", "ja", ""),
        ("zero_divide_00", "ゆみちゃん", "ja", ""),
    ]

    for user_id, nickname, language, basic_response in preferences:
        add_user_preference(user_id, nickname, language, basic_response)
        print(f"Added/Updated: @{user_id}, {nickname}, {language}")

    print("All user preferences have been added/updated.")

if __name__ == "__main__":
    add_preferences_to_db() 