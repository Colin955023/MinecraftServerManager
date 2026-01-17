"""資料模型定義 (package)

此資料夾用於分類資料模型；對外維持舊版匯入相容：
`from src.models import LoaderVersion, ServerConfig`
"""

from .models import LoaderVersion, ServerConfig

__all__ = [
	"LoaderVersion",
	"ServerConfig",
]
