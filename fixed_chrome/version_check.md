# Chrome & ChromeDriverバージョンチェック方法

## 概要
ChromeとChromeDriverのバージョン互換性を確認するためのコマンド集

## バージョン取得コマンド

### ChromeDriverのバージョン取得
```cmd
fixed_chrome\chromedriver\chromedriver-win64\chromedriver.exe --version
```

**出力例:**
```
ChromeDriver 140.0.7339.80 (670b6f192f4668d2ac2c06bd77ec3e4eeda7d648-refs/branch-heads/7339_41@{#3})
```

### Chrome.exeのバージョン取得
```cmd
powershell -Command "(Get-ItemProperty 'fixed_chrome\chrome\chrome-win64\chrome.exe').VersionInfo.FileVersion"
```

**出力例:**
```
140.0.7339.80
```

## バージョン互換性チェック

**現在のバージョン (2025/01/09時点):**
- Chrome.exe: 140.0.7339.80
- ChromeDriver: 140.0.7339.80

✅ **互換性**: 完全一致 - 問題なし

## トラブルシューティング

### Chrome.exeの--versionオプションが応答しない場合
Chrome.exeの`--version`オプションが空の出力を返す場合がありますが、PowerShellの`Get-ItemProperty`を使用することでファイルプロパティから確実にバージョン情報を取得できます。

### バージョン不一致の場合
- ChromeとChromeDriverのメジャーバージョン（最初の3桁）が一致している必要があります
- 不一致の場合は、どちらかを対応するバージョンに更新してください

## 自動チェック用バッチファイル
定期的なバージョンチェックには `check_versions.bat` を使用してください。