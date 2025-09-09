# 固定Chrome環境について

このディレクトリには、プロジェクト専用の固定バージョンのChromeブラウザとChromeDriverが配置されます。

## ディレクトリ構造

```
fixed_chrome/
├── chrome/              # Chrome本体（バイナリ）の配置場所
│   ├── chrome.exe      # （Windows）Chrome実行ファイル
│   └── Application/    # Chrome関連ファイル
├── chromedriver/        # ChromeDriverの配置場所
│   └── chromedriver.exe # ChromeDriver実行ファイル
└── README.md           # このファイル
```

## 使用方法

1. **Chrome本体の配置**
   - Zipファイルから `fixed_chrome/chrome/` にChrome本体を展開してください
   - chrome.exe が `fixed_chrome/chrome/chrome.exe` にあることを確認

2. **ChromeDriverの配置**
   - ChromeDriverのZipファイルから `fixed_chrome/chromedriver/` に展開してください
   - chromedriver.exe が `fixed_chrome/chromedriver/chromedriver.exe` にあることを確認

3. **バージョン確認**
   - Chrome本体とChromeDriverのメジャーバージョンが一致していることを確認してください
   - 例：Chrome 120.x と ChromeDriver 120.x

## 注意事項

- このディレクトリの内容は.gitignoreに追加されているため、リポジトリにはコミットされません
- 他の開発者も同様にこの構造でChrome環境をセットアップする必要があります

## 重要なプロジェクト方針

⚠️ **このプロジェクトでは以下の方針を厳守してください:**

1. **fixed_chrome専用使用**: このプロジェクトでは`fixed_chrome`ディレクトリのChromeのみを使用
2. **他のChromeは使用禁止**: システムにインストール済みの他のChromeブラウザは使用しない
3. **アップデート禁止**: バージョンの一貫性を保つため、ChromeとChromeDriverのアップデートは行わない
4. **バージョン固定**: Chrome 140.0.7339.80 と ChromeDriver 140.0.7339.80 で固定

この方針により、開発環境の一貫性を保ち、予期しない動作変更を防ぎます。

## バージョンチェック方法

バージョン確認には以下のファイルを使用してください：
- `check_versions.bat` - 簡単なバージョンチェック用バッチファイル
- `version_check.md` - 詳細なバージョンチェック方法のドキュメント