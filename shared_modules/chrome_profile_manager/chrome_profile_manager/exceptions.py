"""Chrome Profile Manager 専用例外クラス"""


class ChromeProfileManagerError(Exception):
    """Chrome Profile Manager 基底例外"""
    pass


class ProfileNotFoundError(ChromeProfileManagerError):
    """プロファイルが見つからない場合の例外"""
    pass


class ProfileCreationError(ChromeProfileManagerError):
    """プロファイル作成に失敗した場合の例外"""
    pass


class ChromeLaunchError(ChromeProfileManagerError):
    """Chrome起動に失敗した場合の例外"""
    pass


class ProfileDeleteError(ChromeProfileManagerError):
    """プロファイル削除に失敗した場合の例外"""
    pass