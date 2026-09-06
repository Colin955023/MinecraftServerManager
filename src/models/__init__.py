"""
src/models/__init__.py
資料模型套件
提供 Minecraft 伺服器管理器的資料模型定義與相關類別
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "CatalogOutcomeKind": (".mod_models", "CatalogOutcomeKind"),
    "ConflictType": (".server_models", "ConflictType"),
    "EulaState": (".server_models", "EulaState"),
    "ImportMode": (".server_models", "ImportMode"),
    "ImportManifest": (".server_models", "ImportManifest"),
    "ImportManifestEntry": (".server_models", "ImportManifestEntry"),
    "ImportSourceKind": (".server_models", "ImportSourceKind"),
    "LocalModInfo": (".mod_models", "LocalModInfo"),
    "LocalModMutationResult": (".mod_models", "LocalModMutationResult"),
    "LocalModUpdateCandidate": (".mod_models", "LocalModUpdateCandidate"),
    "LocalModUpdatePlan": (".mod_models", "LocalModUpdatePlan"),
    "ModFileOperationResult": (".mod_models", "ModFileOperationResult"),
    "ModPlatform": (".mod_models", "ModPlatform"),
    "ModStatus": (".mod_models", "ModStatus"),
    "ModrinthVersionLookupResult": (".mod_models", "ModrinthVersionLookupResult"),
    "OnlineDependencyInstallItem": (".mod_models", "OnlineDependencyInstallItem"),
    "OnlineDependencyInstallPlan": (".mod_models", "OnlineDependencyInstallPlan"),
    "OnlineModCompatibilityReport": (".mod_models", "OnlineModCompatibilityReport"),
    "OnlineModInfo": (".mod_models", "OnlineModInfo"),
    "OnlineModVersion": (".mod_models", "OnlineModVersion"),
    "PendingOnlineInstall": (".mod_models", "PendingOnlineInstall"),
    "ProviderCatalogOutcome": (".mod_models", "ProviderCatalogOutcome"),
    "ProviderIdentityEvidence": (".mod_models", "ProviderIdentityEvidence"),
    "ProviderIdentitySnapshot": (".mod_models", "ProviderIdentitySnapshot"),
    "ProviderLifecycle": (".mod_models", "ProviderLifecycle"),
    "ProgressEvent": (".server_models", "ProgressEvent"),
    "ServerConfig": (".server_models", "ServerConfig"),
    "ServerCreationPlan": (".server_models", "ServerCreationPlan"),
    "ServerCreationResult": (".server_models", "ServerCreationResult"),
    "ServerCreationWarning": (".server_models", "ServerCreationWarning"),
    "ServerDiscoveryIssue": (".server_models", "ServerDiscoveryIssue"),
    "ServerDiscoveryReport": (".server_models", "ServerDiscoveryReport"),
    "ServerInspection": (".server_models", "ServerInspection"),
    "ServerInspectionIntent": (".server_models", "ServerInspectionIntent"),
    "ServerLaunchTarget": (".server_models", "ServerLaunchTarget"),
    "ServerImportBatchResult": (".server_models", "ServerImportBatchResult"),
    "ServerImportInspection": (".server_models", "ServerImportInspection"),
    "ServerImportResult": (".server_models", "ServerImportResult"),
    "ServerOperationResult": (".server_models", "ServerOperationResult"),
}

__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
