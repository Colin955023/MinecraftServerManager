"""
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
    "ModStatus": (".mod_models", "ModStatus"),
    "ModPlatform": (".mod_models", "ModPlatform"),
    "LocalModInfo": (".mod_models", "LocalModInfo"),
    "ModFileOperationResult": (".mod_models", "ModFileOperationResult"),
    "LocalModMutationResult": (".mod_models", "LocalModMutationResult"),
    "MODRINTH_HASH_ALGORITHM": (".mod_models", "MODRINTH_HASH_ALGORITHM"),
    "MODRINTH_SEARCH_URL": (".mod_models", "MODRINTH_SEARCH_URL"),
    "ModrinthIdentityCache": (".mod_models", "ModrinthIdentityCache"),
    "ServerInstance": (".server_instance", "ServerInstance"),
    "AbstractReviewEntry": (".mod_management_models", "AbstractReviewEntry"),
    "LocalUpdateReviewEntry": (".mod_management_models", "LocalUpdateReviewEntry"),
    "PendingInstallReviewEntry": (".mod_management_models", "PendingInstallReviewEntry"),
    "PendingOnlineInstall": (".mod_management_models", "PendingOnlineInstall"),
    "ReviewTaskNode": (".mod_management_models", "ReviewTaskNode"),
    "OnlineBrowseRequest": (".mod_management_models", "OnlineBrowseRequest"),
    "OnlineModInfo": (".mod_search_models", "OnlineModInfo"),
    "OnlineModCompatibilityReport": (".mod_search_models", "OnlineModCompatibilityReport"),
    "LocalMetadataEnsureSummary": (".mod_search_models", "LocalMetadataEnsureSummary"),
    "LocalModUpdateCandidate": (".mod_search_models", "LocalModUpdateCandidate"),
    "LocalModUpdatePlan": (".mod_search_models", "LocalModUpdatePlan"),
}

__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
