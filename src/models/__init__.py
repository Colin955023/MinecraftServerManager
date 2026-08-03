"""
src/models/__init__.py
資料模型套件
提供 Minecraft 伺服器管理器的資料模型定義與相關類別。
"""

from __future__ import annotations

from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "ModrinthVersionLookupResult": (".models", "ModrinthVersionLookupResult"),
    "LoaderVersion": (".models", "LoaderVersion"),
    "OnlineModVersion": (".models", "OnlineModVersion"),
    "ResolvedDependencyReference": (".models", "ResolvedDependencyReference"),
    "ServerConfig": (".models", "ServerConfig"),
    "ModStatus": (".models", "ModStatus"),
    "ModPlatform": (".models", "ModPlatform"),
    "LocalModInfo": (".models", "LocalModInfo"),
    "ModFileOperationResult": (".models", "ModFileOperationResult"),
    "LocalModMutationResult": (".models", "LocalModMutationResult"),
    "MODRINTH_HASH_ALGORITHM": (".models", "MODRINTH_HASH_ALGORITHM"),
    "MODRINTH_SEARCH_URL": (".models", "MODRINTH_SEARCH_URL"),
    "ModrinthIdentityCache": (".models", "ModrinthIdentityCache"),
    "AbstractReviewEntry": (".models", "AbstractReviewEntry"),
    "LocalUpdateReviewEntry": (".models", "LocalUpdateReviewEntry"),
    "PendingInstallReviewEntry": (".models", "PendingInstallReviewEntry"),
    "PendingOnlineInstall": (".models", "PendingOnlineInstall"),
    "ReviewTaskNode": (".models", "ReviewTaskNode"),
    "OnlineBrowseRequest": (".models", "OnlineBrowseRequest"),
    "OnlineModInfo": (".models", "OnlineModInfo"),
    "OnlineModCompatibilityReport": (".models", "OnlineModCompatibilityReport"),
    "LocalMetadataEnsureSummary": (".models", "LocalMetadataEnsureSummary"),
    "LocalModUpdateCandidate": (".models", "LocalModUpdateCandidate"),
    "LocalModUpdatePlan": (".models", "LocalModUpdatePlan"),
    "ServerOperationResult": (".models", "ServerOperationResult"),
}

__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
