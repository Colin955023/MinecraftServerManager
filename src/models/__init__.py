"""
src/models/__init__.py
資料模型套件
提供 Minecraft 伺服器管理器的資料模型定義與相關類別
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "CatalogOutcomeKind": (".models", "CatalogOutcomeKind"),
    "ConflictType": (".models", "ConflictType"),
    "EulaState": (".models", "EulaState"),
    "HTTPJSONResponse": (".models", "HTTPJSONResponse"),
    "ImportMode": (".models", "ImportMode"),
    "ImportSourceKind": (".models", "ImportSourceKind"),
    "LoaderInstallerArtifact": (".models", "LoaderInstallerArtifact"),
    "LoaderSpec": (".models", "LoaderSpec"),
    "LoaderVersion": (".models", "LoaderVersion"),
    "LocalModInfo": (".models", "LocalModInfo"),
    "LocalModMutationResult": (".models", "LocalModMutationResult"),
    "LocalModUpdateCandidate": (".models", "LocalModUpdateCandidate"),
    "LocalModUpdatePlan": (".models", "LocalModUpdatePlan"),
    "ModFileOperationResult": (".models", "ModFileOperationResult"),
    "ModPlatform": (".models", "ModPlatform"),
    "ModStatus": (".models", "ModStatus"),
    "ModrinthVersionLookupResult": (".models", "ModrinthVersionLookupResult"),
    "OnlineDependencyInstallItem": (".models", "OnlineDependencyInstallItem"),
    "OnlineDependencyInstallPlan": (".models", "OnlineDependencyInstallPlan"),
    "OnlineModCompatibilityReport": (".models", "OnlineModCompatibilityReport"),
    "OnlineModInfo": (".models", "OnlineModInfo"),
    "OnlineModVersion": (".models", "OnlineModVersion"),
    "OperationResult": (".models", "OperationResult"),
    "PendingOnlineInstall": (".models", "PendingOnlineInstall"),
    "ProviderCatalogOutcome": (".models", "ProviderCatalogOutcome"),
    "ProviderIdentityEvidence": (".models", "ProviderIdentityEvidence"),
    "ProviderIdentitySnapshot": (".models", "ProviderIdentitySnapshot"),
    "ProviderLifecycle": (".models", "ProviderLifecycle"),
    "ResolvedDependencyReference": (".models", "ResolvedDependencyReference"),
    "ServerConfig": (".models", "ServerConfig"),
    "ServerCreationPlan": (".models", "ServerCreationPlan"),
    "ServerCreationResult": (".models", "ServerCreationResult"),
    "ServerCreationWarning": (".models", "ServerCreationWarning"),
    "ServerInspection": (".models", "ServerInspection"),
    "ServerInspectionIntent": (".models", "ServerInspectionIntent"),
    "ServerLaunchTarget": (".models", "ServerLaunchTarget"),
    "ServerImportBatchResult": (".models", "ServerImportBatchResult"),
    "ServerImportInspection": (".models", "ServerImportInspection"),
    "ServerImportResult": (".models", "ServerImportResult"),
    "ServerOperationResult": (".models", "ServerOperationResult"),
    "ServerPropertiesReadStatus": (".models", "ServerPropertiesReadStatus"),
    "ServerPropertiesSnapshot": (".models", "ServerPropertiesSnapshot"),
    "ServerPropertiesUpdateResult": (".models", "ServerPropertiesUpdateResult"),
    "ServerRuntimeEvent": (".models", "ServerRuntimeEvent"),
    "ServerRuntimeEventKind": (".models", "ServerRuntimeEventKind"),
    "ServerRuntimeSnapshot": (".models", "ServerRuntimeSnapshot"),
    "ServerRuntimeState": (".models", "ServerRuntimeState"),
}

__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
