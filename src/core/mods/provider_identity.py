"""Provider-neutral identity lifecycle 與持久化政策"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from src.models import (
    CatalogOutcomeKind,
    ProviderCatalogOutcome,
    ProviderIdentityEvidence,
    ProviderIdentitySnapshot,
    ProviderLifecycle,
)
from src.utils import ProviderIdentityPersistenceError, clean_api_identifier

from .mod_provider_port import ModProviderPort

PROVIDER_IDENTITY_TTL_SECONDS = 12 * 60 * 60
PROVIDER_IDENTITY_MAX_FAILURES = 3
PROVIDER_IDENTITY_RETRY_BASE_SECONDS = 5 * 60
PROVIDER_IDENTITY_RETRY_MAX_SECONDS = 6 * 60 * 60
PROVIDER_IDENTITY_MAX_IDENTIFIERS = 32
PROVIDER_IDENTITY_MAX_SEARCH_TERMS = 8


class ProviderIdentityStorePort(Protocol):
    """以本地 Mod 檔案為 key 的 identity 持久化埠"""

    def load(self, file_path: Path) -> dict[str, Any] | None: ...

    def replace(self, file_path: Path, payload: dict[str, Any]) -> None: ...


class ModIndexProviderIdentityStore:
    """讓 identity owner 使用模組索引持久化，但不洩漏 schema policy"""

    def __init__(self, index_manager: Any) -> None:
        self._index_manager = index_manager

    def load(self, file_path: Path) -> dict[str, Any] | None:
        """
        從 Mod index 讀取 identity payload

        Args:
            file_path: 本地 Mod 檔案路徑

        Returns:
            已存在的 payload；沒有紀錄時回傳 None
        """
        return self._index_manager.get_provider_identity(file_path)

    def replace(self, file_path: Path, payload: dict[str, Any]) -> None:
        """
        透過 Mod index 完整取代 identity payload

        Args:
            file_path: 本地 Mod 檔案路徑
            payload: 要持久化的完整 identity 快照
        """
        target_path = file_path
        if not target_path.exists():
            if target_path.suffix == ".disabled" and target_path.with_suffix("").exists():
                target_path = target_path.with_suffix("")
            elif target_path.with_name(f"{target_path.name}.disabled").exists():
                target_path = target_path.with_name(f"{target_path.name}.disabled")
            else:
                return

        if self._index_manager.replace_provider_identity(target_path, payload) is False:
            if not target_path.exists():
                return
            raise ProviderIdentityPersistenceError(f"provider identity persistence failed: {target_path}")


class ProviderIdentityService:
    """Provider identity 的唯一解析、狀態轉移、投影與持久化 owner"""

    def __init__(
        self,
        *,
        store: ProviderIdentityStorePort,
        catalog: ModProviderPort,
        ttl_seconds: int = PROVIDER_IDENTITY_TTL_SECONDS,
        memory_cache_size: int = 512,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._ttl_seconds = max(0, int(ttl_seconds))
        self._memory_cache_size = max(0, int(memory_cache_size))
        self._memory_cache: OrderedDict[str, ProviderIdentitySnapshot] = OrderedDict()
        self._lock = threading.RLock()

    def load(self, file_path: Path) -> ProviderIdentitySnapshot:
        """
        載入並正規化單一 Mod 檔案的 identity

        Args:
            file_path: 本地 Mod 檔案路徑

        Returns:
            套用 TTL 與 lifecycle policy 後的快照
        """
        return ProviderIdentitySnapshot.from_payload(self._store.load(file_path), ttl_seconds=self._ttl_seconds)

    def resolve(self, evidence: ProviderIdentityEvidence, *, force: bool = False) -> ProviderIdentitySnapshot:
        """
        依線索、快取與 catalog 解析 canonical identity

        Args:
            evidence: 本地 metadata、hash 與搜尋線索
            force: 是否忽略 fresh 或 retry backoff 狀態強制解析

        Returns:
            已持久化成功或保留既有狀態的 identity 快照
        """
        now_ms = int(time.time() * 1000)
        existing = self.load(evidence.file_path)
        if existing.canonical and not force:
            return existing
        if (
            existing.lifecycle in {"retrying", "invalidated"}
            and now_ms < existing.next_retry_not_before_epoch_ms
            and not force
        ):
            return existing
        if evidence.hash_project_id:
            hash_project_id = clean_api_identifier(evidence.hash_project_id)
            return self.commit_found(
                evidence.file_path,
                ProviderCatalogOutcome(
                    "found",
                    project_id=hash_project_id,
                    alias=existing.alias if existing.project_id == hash_project_id else "",
                    display_name=evidence.display_name or existing.display_name,
                    confidence=100,
                ),
                provenance="hash",
                now_epoch_ms=now_ms,
            )
        identifiers = _dedupe(
            (
                evidence.project_id_hint,
                existing.project_id,
                evidence.alias_hint,
                existing.alias,
                *evidence.jar_aliases,
            )
        )[:PROVIDER_IDENTITY_MAX_IDENTIFIERS]
        failure_kinds: list[CatalogOutcomeKind] = []
        for identifier in identifiers:
            cached = self._memory_get(identifier, now_ms)
            outcome = self._catalog.find_projects(identifier, exact=True) if cached is None else cached
            if outcome.canonical:
                return self.commit_found(
                    evidence.file_path,
                    outcome,
                    provenance="exact_lookup",
                    now_epoch_ms=now_ms,
                )
            failure_kinds.append(outcome.kind)
            if outcome.kind in {"transient_failure", "rate_limited", "invalid_response"}:
                return self.commit_failure(evidence, existing, failure_kinds, now_epoch_ms=now_ms)

        for term in _dedupe((*evidence.search_terms, evidence.display_name))[:PROVIDER_IDENTITY_MAX_SEARCH_TERMS]:
            outcome = self._catalog.find_projects(term)
            if outcome.canonical and outcome.confidence >= 70:
                return self.commit_found(
                    evidence.file_path,
                    outcome,
                    provenance="search",
                    now_epoch_ms=now_ms,
                )
            failure_kinds.append(outcome.kind)
            if outcome.kind in {"transient_failure", "rate_limited", "invalid_response"}:
                break

        return self.commit_failure(evidence, existing, failure_kinds, now_epoch_ms=now_ms)

    def resolve_for_local_mod(
        self, local_mod: Any, hash_project_id: str = "", *, force: bool = False
    ) -> ProviderIdentitySnapshot:
        """
        把 LocalModInfo 轉成 evidence 並解析；不修改 consumer object

        Args:
            local_mod: 提供本地路徑、名稱與既有 provider 欄位的 Mod 物件
            hash_project_id: Hash API 已確認的專案 ID
            force: 是否忽略快取或 backoff 限制強制解析

        Returns:
            解析並持久化後的 identity 快照
        """
        raw_file_path = str(getattr(local_mod, "file_path", "") or "").strip()
        if not raw_file_path:
            raise ValueError("provider identity resolution requires local_mod.file_path")
        file_path = Path(raw_file_path)
        if not file_path.exists():
            if file_path.suffix == ".disabled" and file_path.with_suffix("").exists():
                file_path = file_path.with_suffix("")
            elif file_path.with_name(f"{file_path.name}.disabled").exists():
                file_path = file_path.with_name(f"{file_path.name}.disabled")
        filename = str(getattr(local_mod, "filename", "") or "").strip()
        return self.resolve(
            ProviderIdentityEvidence(
                file_path=file_path,
                project_id_hint=str(getattr(local_mod, "platform_id", "") or "").strip(),
                alias_hint=str(getattr(local_mod, "platform_slug", "") or "").strip(),
                display_name=str(getattr(local_mod, "name", "") or "").strip(),
                search_terms=(filename, str(getattr(local_mod, "name", "") or "")),
                hash_project_id=clean_api_identifier(hash_project_id),
            ),
            force=force,
        )

    def commit_found(
        self,
        file_path: Path,
        outcome: ProviderCatalogOutcome,
        *,
        provenance: str,
        now_epoch_ms: int | None = None,
    ) -> ProviderIdentitySnapshot:
        """
        提交成功解析的 canonical identity

        Args:
            file_path: identity 所屬的本地 Mod 檔案
            outcome: 含 canonical project ID 的 catalog 結果
            provenance: 本次解析依據
            now_epoch_ms: 選用的觀測時間

        Returns:
            已持久化且標記 fresh 的快照
        """
        if not outcome.canonical:
            raise ValueError("canonical provider identity requires project_id")
        now_ms = int(now_epoch_ms if now_epoch_ms is not None else time.time() * 1000)
        snapshot = ProviderIdentitySnapshot(
            provider=clean_api_identifier(outcome.provider).lower() or "modrinth",
            project_id=clean_api_identifier(outcome.project_id),
            alias=clean_api_identifier(outcome.alias),
            display_name=clean_api_identifier(outcome.display_name),
            provenance=clean_api_identifier(provenance) or "catalog",
            lifecycle="fresh",
            observed_at_epoch_ms=now_ms,
            resolved_at_epoch_ms=now_ms,
        )
        self._persist(file_path, snapshot)
        self._memory_put(snapshot)
        return snapshot

    def commit_failure(
        self,
        evidence: ProviderIdentityEvidence,
        existing: ProviderIdentitySnapshot,
        failure_kinds: list[CatalogOutcomeKind],
        *,
        now_epoch_ms: int | None = None,
    ) -> ProviderIdentitySnapshot:
        """
        依失敗種類更新 retry、missing 或 invalidated 狀態

        Args:
            evidence: 本次使用的解析線索
            existing: 解析前的 identity 快照
            failure_kinds: 依發生順序記錄的 catalog 結果種類
            now_epoch_ms: 選用的觀測時間

        Returns:
            已持久化的失敗生命週期快照
        """
        now_ms = int(now_epoch_ms if now_epoch_ms is not None else time.time() * 1000)
        has_evidence = bool(
            evidence.project_id_hint
            or evidence.alias_hint
            or evidence.jar_aliases
            or evidence.search_terms
            or evidence.display_name
            or existing.project_id
            or existing.alias
        )
        attempted = bool(failure_kinds)
        failures = existing.failure_count + (1 if attempted else 0)
        transport_failure = any(kind in {"transient_failure", "rate_limited"} for kind in failure_kinds)
        lifecycle: ProviderLifecycle
        if not has_evidence:
            lifecycle = "missing"
        elif failures >= PROVIDER_IDENTITY_MAX_FAILURES and not transport_failure:
            lifecycle = "invalidated"
        else:
            lifecycle = "retrying"
        delay_seconds = (
            PROVIDER_IDENTITY_RETRY_MAX_SECONDS
            if "rate_limited" in failure_kinds
            else min(
                PROVIDER_IDENTITY_RETRY_MAX_SECONDS,
                PROVIDER_IDENTITY_RETRY_BASE_SECONDS * (2 ** max(0, failures - 1)),
            )
        )
        snapshot = replace(
            existing,
            provider=existing.provider if existing.provider != "local" else "modrinth" if has_evidence else "local",
            project_id=existing.project_id or clean_api_identifier(evidence.project_id_hint),
            alias=existing.alias or clean_api_identifier(evidence.alias_hint) or next(iter(evidence.jar_aliases), ""),
            display_name=existing.display_name or clean_api_identifier(evidence.display_name),
            provenance=f"catalog_{failure_kinds[-1]}" if attempted else "unresolved",
            lifecycle=lifecycle,
            observed_at_epoch_ms=now_ms,
            failure_count=failures,
            next_retry_not_before_epoch_ms=now_ms + delay_seconds * 1000 if lifecycle != "missing" else 0,
        )
        self._persist(evidence.file_path, snapshot)
        return snapshot

    def project(self, target: Any, snapshot: ProviderIdentitySnapshot) -> None:
        """
        唯一允許把 identity snapshot 投影到 LocalModInfo 的入口，包含清除舊 alias

        Args:
            target: 要更新 provider 顯示欄位的 consumer 物件
            snapshot: 作為唯一資料來源的 identity 快照
        """
        target.provider_identity = snapshot
        target.platform_id = snapshot.project_id if snapshot.canonical else ""
        target.platform_slug = snapshot.alias

    def _persist(self, file_path: Path, snapshot: ProviderIdentitySnapshot) -> None:
        self._store.replace(file_path, snapshot.as_payload())

    def _memory_get(self, identifier: str, now_ms: int) -> ProviderCatalogOutcome | None:
        key = _provider_cache_key("modrinth", identifier)
        with self._lock:
            snapshot = self._memory_cache.get(key)
            if snapshot is None or now_ms - snapshot.resolved_at_epoch_ms > self._ttl_seconds * 1000:
                self._memory_cache.pop(key, None)
                return None
            self._memory_cache.move_to_end(key)
        return ProviderCatalogOutcome(
            "found",
            provider=snapshot.provider,
            project_id=snapshot.project_id,
            alias=snapshot.alias,
            display_name=snapshot.display_name,
            confidence=100,
        )

    def _memory_put(self, snapshot: ProviderIdentitySnapshot) -> None:
        if self._memory_cache_size <= 0:
            return
        with self._lock:
            for key in _dedupe((snapshot.project_id, snapshot.alias)):
                normalized = _provider_cache_key(snapshot.provider, key)
                self._memory_cache[normalized] = snapshot
                self._memory_cache.move_to_end(normalized)
            while len(self._memory_cache) > self._memory_cache_size:
                self._memory_cache.popitem(last=False)


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(cleaned for value in values if (cleaned := clean_api_identifier(value))))


def _provider_cache_key(provider: str, identifier: str) -> str:
    return f"{clean_api_identifier(provider).lower()}:{clean_api_identifier(identifier).lower()}"


__all__ = ["ModIndexProviderIdentityStore", "ProviderIdentityService"]
