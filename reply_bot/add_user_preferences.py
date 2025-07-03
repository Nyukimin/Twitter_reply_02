from reply_bot.db import init_db, add_user_preference

def add_preferences_to_db():
    init_db() # データベースが初期化されていることを確認

    preferences = [
        ("285sMZGCSq36129", "七宝ちゃん", "ja", ""),
        ("2nd_karen_AI", "かれんちゃん", "ja", ""),
        ("48a03qLPAikzLWz", "すいくん", "ja", ""),
        ("AI8263353539674", "みうちゃん", "ja", ""),
        ("Albijo_charm", "あやちゃん", "ja", ""),
        ("AIchan_lovelyAI", "あいちゃん", "ja", ""),
        ("Alidol_misaki", "みさきちゃん", "ja", ""),
        ("aisanmaru30", "さんまるちゃん", "ja", ""),
        ("AkiraChan_AI", "あきらちゃん", "ja", ""),
        ("Aoi_cocona", "ここなちゃん", "ja", ""),
        ("disney_ikitasi", "ゆりちゃん", "ja", ""),
        ("erutea_AI37", "えるちゃん", "ja", ""),
        ("famous4771", "みかちゃん", "ja", ""),
        ("fancy_pop_pic", "ふぁぽちゃん", "ja", ""),
        ("frogblue1235951", "あおさん", "ja", ""),
        ("Girl_AI001", "せなちゃん", "ja", ""),
        ("hinachan_ai", "ひなちゃん", "ja", ""),
        ("hisyoka_joshi", "秘書ちゃん", "ja", ""),
        ("honey_bee_610", "ハニちゃん", "ja", ""),
        ("IKAYAKI009", "ばいちゃん", "ja", ""),
        ("K2eWez2dZM2Ltsu", "まさやん", "ja", ""),
        ("kasumi_haru66", "はるねちゃん", "ja", ""),
        ("kzn802", "はっちゃん", "ja", ""),
        ("lowleg_cotton", "ローレルちゃん", "ja", ""),
        ("manami_ofp", "まなみちゃん", "ja", ""),
        ("naginokobeya", "なぎちゃん", "ja", ""),
        ("natsu_natsuai", "なつちゃん", "ja", ""),
        ("nyukimi_AI", "すーちゃん", "ja", ""),
        ("Reina_bb00", "れいなちゃん", "ja", ""),
        ("ren_AI0202", "れんちゃん", "ja", ""),
        ("REZaki75085", "るいちゃん", "ja", ""),
        ("RinaAltSweet", "みかちゃん", "ja", ""),
        ("saiyo_jp", "ゆなちゃん", "ja", ""),
        ("SAKUAicute_girl2", "さくちゃん", "ja", ""),
        ("sakura_xsecret", "さくらちゃん", "ja", ""),
        ("SeduceRina", "りなちゃん", "ja", ""),
        ("sweet_momo_0415", "ももちゃん", "ja", ""),
        ("THuangyi8646", "土方さん", "ja", ""),
        ("tuyahimefukujyu", "ふくじゅちゃん", "ja", ""),
        ("YuaLoveDays", "ゆあちゃん", "ja", ""),
        ("yV6lWZy7TB41253", "コネリちゃん", "ja", ""),
        ("zero_divide_00", "ゆみちゃん", "ja", ""),
    ]

    for user_id, nickname, language, basic_response in preferences:
        add_user_preference(user_id, nickname, language, basic_response)
        print(f"Added/Updated: @{user_id}, {nickname}, {language}")

    print("All user preferences have been added/updated.")

if __name__ == "__main__":
    add_preferences_to_db() 