"""Chrome Profile Manager - プロファイル管理とChrome起動の統合ライブラリ"""

from .manager import ProfiledChromeManager
from .exceptions import ProfileNotFoundError, ProfileCreationError

__version__ = "1.0.0"
__all__ = ["ProfiledChromeManager", "ProfileNotFoundError", "ProfileCreationError"]