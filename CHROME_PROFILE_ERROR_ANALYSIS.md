# Chrome Profile エラー分析レポート

## 問題の概要

他のPCでプロジェクトを実行した際に、Chromeプロファイルのロックに関するエラーが発生しています。

## エラーログ分析

### 主要なエラー

1. **`session not created: probably user data directory is already in use`**
   - ChromeDriverがプロファイルディレクトリにアクセスできない
   - プロファイルが既に使用中と判断されている

2. **`PermissionError: [Errno 13] assume access denied`**
   - psutilがプロセス情報（コマンドライン）を読み取れない
   - Windows特有の権限問題

## 根本原因

1. **プロセス権限の問題**
   - Windows環境で、psutilが他のプロセスのコマンドライン引数を読み取る際に権限エラーが発生
   - このため、どのChromeプロセスが特定のプロファイルを使用しているか判定できない

2. **プロファイルロックの残存**
   - Chromeプロセスが正常に終了せず、プロファイルのロックファイルが残る
   - `kill_chrome_using_profile`メソッドが正常に動作しない

3. **ChromeDriverManager の副作用**
   - ChromeDriverManagerがインストール時に余計なChromeプロセスを起動する可能性

## 解決策

### 1. 権限エラーの回避

`manager.py`の`kill_chrome_using_profile`メソッドを改善：

```python
def kill_chrome_using_profile(self, profile_path: str, timeout: int = 10) -> list[int]:
    """特定プロファイルを使用しているChromeプロセスのみを終了
    
    Windowsの権限エラーに対応した改善版
    """
    killed_pids = []
    
    try:
        # 正規化されたプロファイルパスを取得
        normalized_profile_path = str(Path(profile_path).resolve())
        self.logger.debug(f"プロファイルパスを検索: {normalized_profile_path}")
        
        # Windows環境での権限エラー対策
        import platform
        is_windows = platform.system() == 'Windows'
        
        # プロセス検索
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                proc_info = proc.info
                name = (proc_info.get('name') or "").lower()
                
                if 'chrome' not in name and 'chromedriver' not in name:
                    continue
                    
                # Windows環境で権限エラーが発生した場合の処理
                cmdline = None
                try:
                    cmdline = proc_info.get('cmdline')
                except (psutil.AccessDenied, PermissionError) as e:
                    if is_windows:
                        # Windows環境での代替手段
                        try:
                            # WMIを使用してコマンドラインを取得
                            cmdline = self._get_cmdline_via_wmi(proc.pid)
                        except:
                            # それでも失敗した場合はスキップ
                            self.logger.debug(f"PID {proc.pid} のcmdline取得失敗: {e}")
                            continue
                    else:
                        continue
                
                if cmdline:
                    cmdline_str = " ".join(cmdline) if isinstance(cmdline, list) else str(cmdline)
                    
                    # プロファイルパスの検索（大文字小文字を無視）
                    if normalized_profile_path.lower() in cmdline_str.lower():
                        self.logger.info(f"プロファイル使用中のプロセスを発見: PID={proc.pid}")
                        self._terminate_process_safely(proc, timeout)
                        killed_pids.append(proc.pid)
                        
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except Exception as e:
                self.logger.debug(f"プロセス確認中のエラー: {e}")
                
    except Exception as e:
        self.logger.error(f"特定プロファイルのChrome終了エラー: {e}")
        
    return killed_pids

def _get_cmdline_via_wmi(self, pid: int) -> list:
    """WMIを使用してプロセスのコマンドラインを取得（Windows専用）"""
    try:
        import subprocess
        cmd = f'wmic process where ProcessId={pid} get CommandLine /format:list'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        for line in result.stdout.split('\n'):
            if line.startswith('CommandLine='):
                cmdline = line.replace('CommandLine=', '').strip()
                return cmdline.split() if cmdline else []
    except:
        pass
    return []
```

### 2. より強力なロックファイルクリーンアップ

```python
def _cleanup_profile_locks(self, profile_path: str):
    """プロファイルディレクトリのロックファイルを強制的にクリーンアップ"""
    profile_dir = Path(profile_path)
    if not profile_dir.exists():
        return
        
    # ロックファイルパターンを拡張
    lock_patterns = [
        'Singleton*',
        '*.lock',
        'lockfile*', 
        'parent.lock',
        '*/LOCK',
        'SingletonLock',
        'SingletonSocket',
        'SingletonCookie',
        '.org.chromium.Chromium.*'  # Linux/Mac用
    ]
    
    for pattern in lock_patterns:
        # トップレベル
        for lock_file in profile_dir.glob(pattern):
            self._force_remove_file(lock_file)
            
        # サブディレクトリ
        for lock_file in profile_dir.glob(f"**/{pattern}"):
            self._force_remove_file(lock_file)
            
def _force_remove_file(self, file_path: Path):
    """ファイルを強制的に削除（Windows権限対応）"""
    if not file_path.exists():
        return
        
    try:
        if file_path.is_file():
            # Windows環境での権限変更
            import platform
            if platform.system() == 'Windows':
                import stat
                try:
                    file_path.chmod(stat.S_IWRITE)
                except:
                    pass
            file_path.unlink()
            self.logger.debug(f"ロックファイル削除: {file_path}")
    except Exception as e:
        # 管理者権限での削除を試みる（Windows）
        if platform.system() == 'Windows':
            try:
                import subprocess
                subprocess.run(['del', '/F', str(file_path)], shell=True, check=False)
            except:
                pass
```

### 3. プロファイル起動前の完全クリーンアップ

```python
def _pre_launch_cleanup(self, profile_path: str):
    """Chrome起動前の完全なクリーンアップ処理"""
    import platform
    is_windows = platform.system() == 'Windows'
    
    # 1. プロファイル特定のプロセス終了
    killed_pids = self.kill_chrome_using_profile(profile_path, timeout=5)
    if killed_pids:
        time.sleep(1)  # プロセス終了を待つ
        
    # 2. Windows環境での追加処理
    if is_windows:
        # taskkillを使用した強制終了
        try:
            import subprocess
            # プロファイルパスを含むChromeプロセスを検索して終了
            ps_cmd = f'powershell "Get-Process chrome -ErrorAction SilentlyContinue | Where-Object {{$_.CommandLine -like \'*{profile_path}*\'}} | Stop-Process -Force"'
            subprocess.run(ps_cmd, shell=True, capture_output=True, timeout=5)
        except:
            pass
            
    # 3. ロックファイルの完全削除
    self._cleanup_profile_locks(profile_path)
    
    # 4. プロファイルディレクトリの権限確認と修正
    if is_windows:
        profile_dir = Path(profile_path)
        if profile_dir.exists():
            try:
                import subprocess
                # ディレクトリの所有権を取得
                subprocess.run(f'takeown /F "{profile_dir}" /R /D Y', shell=True, capture_output=True, timeout=10)
                # フルコントロール権限を付与
                subprocess.run(f'icacls "{profile_dir}" /grant *S-1-5-32-545:F /T', shell=True, capture_output=True, timeout=10)
            except:
                pass
```

## 推奨される実装手順

1. **管理者権限での実行を推奨**
   - Windowsでは管理者権限で実行することで多くの権限問題を回避可能

2. **エラーハンドリングの強化**
   - 権限エラーに対する代替処理を実装
   - WMIやPowerShellを使用した代替手段

3. **プロファイル再作成オプション**
   - ロック問題が解決しない場合は自動的にプロファイルを再作成

## テスト用スクリプト

```python
# test_chrome_profile_fix.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared_modules.chrome_profile_manager import ProfiledChromeManager
import logging

logging.basicConfig(level=logging.DEBUG)

def test_with_cleanup():
    manager = ProfiledChromeManager()
    profile_name = "twitter_main"
    
    try:
        # 強制的にクリーンアップしてから起動
        driver = manager.create_and_launch(
            profile_name=profile_name,
            force_recreate=False,
            fallback_to_temp=True,
            max_retries=3,
            headless=False
        )
        
        print("Chrome起動成功！")
        input("Enterキーを押して終了...")
        driver.quit()
        
    except Exception as e:
        print(f"エラー: {e}")
        
if __name__ == "__main__":
    test_with_cleanup()
```

## 結論

このエラーは主にWindows環境での権限問題に起因しています。上記の解決策を実装することで、より堅牢なChromeプロファイル管理が可能になります。

### 即座の対処法

1. **管理者権限でコマンドプロンプトを起動**
2. **既存のChromeプロセスを全て終了**
   ```
   taskkill /F /IM chrome.exe
   taskkill /F /IM chromedriver.exe
   ```
3. **プロファイルディレクトリを削除して再作成**
   ```
   rmdir /S /Q profiles\twitter_main
   ```
4. **再度実行**

これらの対策により、プロファイルロック問題を解決できるはずです。