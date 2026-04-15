"""Provider metadata 契約工具。

集中管理本地模組與索引之間的 provider metadata 結構，避免多處各自組裝
`platform`、`project_id`、`slug`、`project_name` 的 payload。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import HTTPUtils

MODRINTH_PROJECT_DETAIL_URL_TEMPLATE = "https://api.modrinth.com/v2/project/{project_id}"
MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS = 12
PROVIDER_METADATA_TTL_SECONDS = 12 * 60 * 60
PROVIDER_REVALIDATION_RETRY_BASE_SECONDS = 60
PROVIDER_REVALIDATION_RETRY_MAX_SECONDS = 30 * 60
PROVIDER_REVALIDATION_INVALIDATE_FAILURE_THRESHOLD = 4
PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN = 24
_MODRINTH_PROVIDER_RECORD_CACHE: dict[str, ProviderMetadataRecord] = {}


@dataclass(slots=True)
class ProviderMetadataRecord:
    """正規化後的 provider metadata。"""

    platform: str = "local"
    project_id: str = ""
    slug: str = ""
    project_name: str = ""

    @classmethod
    def from_cached(cls, raw: dict[str, Any] | None) -> ProviderMetadataRecord:
        """從快取 payload 還原 provider metadata。

        Args:
            raw: 快取中的原始資料。

        Returns:
            正規化後的 provider metadata。
        """

        if not isinstance(raw, dict):
            return cls()
        return cls.from_values(
            platform=raw.get("platform", ""),
            project_id=raw.get("project_id", ""),
            slug=raw.get("slug", ""),
            project_name=raw.get("project_name", ""),
        )

    @classmethod
    def from_values(
        cls,
        *,
        platform: str | None = None,
        project_id: str | None = None,
        slug: str | None = None,
        project_name: str | None = None,
    ) -> ProviderMetadataRecord:
        """以原始欄位值建立正規化後的 provider metadata。

        Args:
            platform: provider 平台名稱。
            project_id: project id。
            slug: 專案 slug。
            project_name: 專案顯示名稱。

        Returns:
            正規化後的 provider metadata。
        """

        clean_project_id = str(project_id or "").strip()
        clean_slug = str(slug or "").strip()
        clean_project_name = str(project_name or "").strip()
        clean_platform = str(platform or "").strip().lower()
        if clean_platform not in {"modrinth", "local"}:
            clean_platform = "modrinth" if clean_project_id else "local"
        return cls(
            platform=clean_platform, project_id=clean_project_id, slug=clean_slug, project_name=clean_project_name
        )

    @property
    def is_modrinth(self) -> bool:
        return self.platform == "modrinth"

    def as_cache_payload(self) -> dict[str, str]:
        """轉成可寫入快取的精簡 payload。

        Returns:
            只包含已知欄位的字典。
        """

        payload = {"platform": self.platform}
        if self.project_id:
            payload["project_id"] = self.project_id
        if self.slug:
            payload["slug"] = self.slug
        if self.project_name:
            payload["project_name"] = self.project_name
        return payload


@dataclass(slots=True)
class LocalProviderEnsureResult:
    """本地 provider metadata ensure 結果。"""

    record: ProviderMetadataRecord
    source: str = "unresolved"
    resolved: bool = False
    lifecycle_state: str = "missing"


def _parse_resolved_at_epoch_ms(raw: dict[str, Any] | None) -> int | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("resolved_at_epoch_ms")
    if value in (None, ""):
        return None
    try:
        resolved_at = int(str(value).strip())
    except TypeError, ValueError:
        return None
    return resolved_at if resolved_at > 0 else None


def is_cached_provider_metadata_fresh(
    raw: dict[str, Any] | None, *, ttl_seconds: int = PROVIDER_METADATA_TTL_SECONDS
) -> bool:
    """判斷快取 provider metadata 是否仍在 freshness 視窗內。

    Args:
        raw: 原始快取資料。
        ttl_seconds: 視為新鮮的存活秒數。

    Returns:
        若快取仍有效則回傳 True，否則回傳 False。

    相容舊資料：若缺少 `resolved_at_epoch_ms`，視為 legacy cache，暫時視為 fresh。
    """
    if not isinstance(raw, dict) or not raw:
        return False
    resolved_at_epoch_ms = _parse_resolved_at_epoch_ms(raw)
    if resolved_at_epoch_ms is None:
        return True
    ttl_ms = max(0, int(ttl_seconds)) * 1000
    now_ms = int(time.time() * 1000)
    return now_ms - resolved_at_epoch_ms <= ttl_ms


def fetch_modrinth_project_detail(
    identifier: str, *, timeout: int = MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS
) -> dict[str, Any] | None:
    """依 project id 或 slug 取得 Modrinth 專案詳細資訊。

    Args:
        identifier: Modrinth project id 或 slug。
        timeout: HTTP 請求逾時秒數。

    Returns:
        專案詳細資訊，找不到時回傳 None。
    """
    clean_identifier = str(identifier or "").strip()
    if not clean_identifier:
        return None
    response = HTTPUtils.get_json(
        url=MODRINTH_PROJECT_DETAIL_URL_TEMPLATE.format(project_id=clean_identifier),
        headers=HTTPUtils.get_default_headers(),
        timeout=timeout,
        suppress_status_codes={404},
    )
    if not isinstance(response, dict):
        return None
    return response


def _remember_provider_record(*keys: str, record: ProviderMetadataRecord) -> ProviderMetadataRecord:
    for key in keys:
        normalized_key = str(key or "").strip().lower()
        if normalized_key:
            _MODRINTH_PROVIDER_RECORD_CACHE[normalized_key] = record
    return record


def resolve_modrinth_provider_record(
    identifier: str, *, search_fallback: Callable[[str], ProviderMetadataRecord | None] | None = None
) -> ProviderMetadataRecord:
    """將 project id / slug 正規化為 canonical provider record。

    Args:
        identifier: 待解析的 project id 或 slug。
        search_fallback: 可選的替代解析流程。

    Returns:
        正規化後的 provider metadata 記錄。
    """
    clean_identifier = str(identifier or "").strip()
    if not clean_identifier:
        return ProviderMetadataRecord()
    cache_key = clean_identifier.lower()
    cached_record = _MODRINTH_PROVIDER_RECORD_CACHE.get(cache_key)
    if cached_record is not None:
        return cached_record
    response = fetch_modrinth_project_detail(clean_identifier)
    if response:
        resolved_record = ProviderMetadataRecord.from_values(
            platform="modrinth",
            project_id=response.get("id", clean_identifier),
            slug=response.get("slug", clean_identifier),
            project_name=response.get("title", "")
            or response.get("name", "")
            or response.get("slug", "")
            or clean_identifier,
        )
        return _remember_provider_record(
            clean_identifier, resolved_record.project_id, resolved_record.slug, record=resolved_record
        )
    if search_fallback is not None:
        fallback_record = search_fallback(clean_identifier)
        if fallback_record is not None and (fallback_record.project_id or fallback_record.slug):
            resolved_fallback = ProviderMetadataRecord.from_values(
                platform=fallback_record.platform,
                project_id=fallback_record.project_id,
                slug=fallback_record.slug or clean_identifier,
                project_name=fallback_record.project_name,
            )
            return _remember_provider_record(
                clean_identifier, resolved_fallback.project_id, resolved_fallback.slug, record=resolved_fallback
            )
    # 僅快取成功解析的結果，保留未解析記錄的處理彈性。
    return ProviderMetadataRecord.from_values(slug=clean_identifier)


def ensure_local_mod_provider_record(
    *,
    platform_id: str | None = None,
    platform_slug: str | None = None,
    project_name: str | None = None,
    identifier_resolver: Callable[[str], ProviderMetadataRecord] | None = None,
    fallback_resolver: Callable[[], ProviderMetadataRecord | None] | None = None,
) -> LocalProviderEnsureResult:
    """以固定順序確保本地模組 provider metadata。

    Args:
        platform_id: 已知的 platform id。
        platform_slug: 已知的 platform slug。
        project_name: 模組顯示名稱。
        identifier_resolver: 以 identifier 解析 provider record 的函式。
        fallback_resolver: 最後備援的解析函式。

    Returns:
        本地 provider metadata 的確保結果。

    決策順序：
    1) 既有 platform_id / platform_slug
    2) identifier_resolver（可選，通常用於 canonical slug 補齊）
    3) fallback_resolver（可選，通常用於本地檔名/名稱查詢）
    """
    clean_project_id = str(platform_id or "").strip()
    clean_slug = str(platform_slug or "").strip()
    clean_project_name = str(project_name or "").strip()
    if clean_project_id and clean_slug:
        record = ProviderMetadataRecord.from_values(
            project_id=clean_project_id, slug=clean_slug, project_name=clean_project_name
        )
        return LocalProviderEnsureResult(
            record=record, source="cached_provider", resolved=True, lifecycle_state=PROVIDER_LIFECYCLE_FRESH
        )
    candidate_identifier = clean_project_id or clean_slug
    if candidate_identifier and identifier_resolver is not None:
        resolved_record = identifier_resolver(candidate_identifier)
        merged_record = ProviderMetadataRecord.from_values(
            project_id=resolved_record.project_id,
            slug=resolved_record.slug or clean_slug,
            project_name=resolved_record.project_name or clean_project_name,
        )
        if merged_record.project_id or (merged_record.slug and fallback_resolver is None):
            resolved = bool(merged_record.project_id)
            return LocalProviderEnsureResult(
                record=merged_record,
                source="cached_provider" if clean_project_id or clean_slug else "identifier_lookup",
                resolved=resolved,
                lifecycle_state=PROVIDER_LIFECYCLE_FRESH if resolved else PROVIDER_LIFECYCLE_MISSING,
            )
    if fallback_resolver is not None:
        fallback_record = fallback_resolver()
        if fallback_record is not None and (fallback_record.project_id or fallback_record.slug):
            merged_fallback = ProviderMetadataRecord.from_values(
                project_id=fallback_record.project_id,
                slug=fallback_record.slug,
                project_name=fallback_record.project_name or clean_project_name,
            )
            resolved = bool(merged_fallback.project_id)
            return LocalProviderEnsureResult(
                record=merged_fallback,
                source="lookup",
                resolved=resolved,
                lifecycle_state=PROVIDER_LIFECYCLE_FRESH if resolved else PROVIDER_LIFECYCLE_MISSING,
            )
    if clean_project_id or clean_slug:
        record = ProviderMetadataRecord.from_values(
            project_id=clean_project_id, slug=clean_slug, project_name=clean_project_name
        )
        resolved = bool(record.project_id)
        return LocalProviderEnsureResult(
            record=record,
            source="cached_provider",
            resolved=resolved,
            lifecycle_state=PROVIDER_LIFECYCLE_FRESH if resolved else PROVIDER_LIFECYCLE_MISSING,
        )
    return LocalProviderEnsureResult(
        record=ProviderMetadataRecord.from_values(project_name=clean_project_name),
        source="unresolved",
        resolved=False,
        lifecycle_state=PROVIDER_LIFECYCLE_MISSING,
    )


def apply_provider_metadata(target: Any, provider_metadata: ProviderMetadataRecord) -> bool:
    """將 provider metadata 套用到本地模組物件。

    Args:
        target: 目標物件。
        provider_metadata: 要套用的 provider metadata。

    Returns:
        若有修改目標物件則回傳 True，否則回傳 False。
    """
    changed = False
    project_id = provider_metadata.project_id
    if project_id and getattr(target, "platform_id", "") != project_id:
        target.platform_id = project_id
        changed = True
    slug = provider_metadata.slug
    if slug and getattr(target, "platform_slug", "") != slug:
        target.platform_slug = slug
        changed = True
    return changed


PROVIDER_LIFECYCLE_FRESH = "fresh"
PROVIDER_LIFECYCLE_STALE = "stale"
PROVIDER_LIFECYCLE_MISSING = "missing"
PROVIDER_LIFECYCLE_RETRYING = "retrying"
PROVIDER_LIFECYCLE_INVALIDATED = "invalidated"


def _parse_positive_int(raw_value: Any) -> int:
    try:
        parsed = int(str(raw_value or "").strip())
    except TypeError, ValueError:
        return 0
    return parsed if parsed > 0 else 0


def compute_provider_revalidation_backoff_seconds(
    failure_count: int,
    *,
    base_seconds: int = PROVIDER_REVALIDATION_RETRY_BASE_SECONDS,
    max_seconds: int = PROVIDER_REVALIDATION_RETRY_MAX_SECONDS,
) -> int:
    """依連續失敗次數計算 retry backoff 秒數。

    Args:
        failure_count: 連續失敗次數。
        base_seconds: 基礎退避秒數。
        max_seconds: 最大退避秒數。

    Returns:
        計算後的退避秒數。
    """
    normalized_failures = max(1, int(failure_count))
    normalized_base = max(1, int(base_seconds))
    normalized_max = max(normalized_base, int(max_seconds))
    backoff = normalized_base * 2 ** (normalized_failures - 1)
    return min(normalized_max, backoff)


def is_provider_revalidation_retry_due(raw: dict[str, Any] | None, *, now_epoch_ms: int | None = None) -> bool:
    """判斷 provider metadata 是否已到可重試時間。

    Args:
        raw: 原始 provider metadata。
        now_epoch_ms: 指定的目前時間毫秒值。

    Returns:
        若已到可重試時間則回傳 True，否則回傳 False。
    """
    if not isinstance(raw, dict):
        return True
    next_retry_not_before_epoch_ms = _parse_positive_int(raw.get("next_retry_not_before_epoch_ms"))
    if next_retry_not_before_epoch_ms <= 0:
        return True
    now_ms = int(now_epoch_ms if now_epoch_ms is not None else time.time() * 1000)
    return now_ms >= next_retry_not_before_epoch_ms


def should_attempt_provider_revalidation(
    raw: dict[str, Any] | None,
    *,
    attempted_count: int,
    max_attempts: int = PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN,
    now_epoch_ms: int | None = None,
) -> tuple[bool, str]:
    """判斷本輪是否應嘗試 stale provider metadata 重查。

    Args:
        raw: 原始 provider metadata。
        attempted_count: 本輪已嘗試次數。
        max_attempts: 本輪最大嘗試次數。
        now_epoch_ms: 指定的目前時間毫秒值。

    Returns:
        `(是否嘗試, 原因碼)` 的判斷結果。

    回傳 `(should_attempt, reason)`：
    - `(False, "batch_limit")`: 本輪重查已達批次上限。
    - `(False, "backoff")`: 尚未到下一次可重試時間。
    - `(True, "due")`: 允許本輪執行重查。
    """
    normalized_max_attempts = max(1, int(max_attempts))
    if int(attempted_count) >= normalized_max_attempts:
        return (False, "batch_limit")
    if not is_provider_revalidation_retry_due(raw, now_epoch_ms=now_epoch_ms):
        return (False, "backoff")
    return (True, "due")


def register_provider_revalidation_failure(
    raw: dict[str, Any] | None, *, now_epoch_ms: int | None = None
) -> dict[str, Any]:
    """記錄 provider revalidation 失敗並產生退避欄位。

    Args:
        raw: 原始 provider metadata。
        now_epoch_ms: 指定的目前時間毫秒值。

    Returns:
        更新後的 payload。
    """
    payload = dict(raw) if isinstance(raw, dict) else {}
    now_ms = int(now_epoch_ms if now_epoch_ms is not None else time.time() * 1000)
    failure_count = _parse_positive_int(payload.get("stale_revalidation_failures")) + 1
    retry_delay_seconds = compute_provider_revalidation_backoff_seconds(failure_count)
    next_retry_not_before_epoch_ms = now_ms + retry_delay_seconds * 1000
    lifecycle_state = (
        PROVIDER_LIFECYCLE_INVALIDATED
        if failure_count >= PROVIDER_REVALIDATION_INVALIDATE_FAILURE_THRESHOLD
        else PROVIDER_LIFECYCLE_RETRYING
    )
    payload["stale_revalidation_failures"] = str(failure_count)
    payload["last_revalidation_failed_at_epoch_ms"] = str(now_ms)
    payload["next_retry_not_before_epoch_ms"] = str(next_retry_not_before_epoch_ms)
    payload["lifecycle_state"] = lifecycle_state
    return payload


def register_provider_revalidation_success(
    raw: dict[str, Any] | None, *, now_epoch_ms: int | None = None
) -> dict[str, Any]:
    """重置 provider revalidation 失敗計數並恢復 lifecycle 狀態。

    Args:
        raw: 原始 provider metadata。
        now_epoch_ms: 指定的目前時間毫秒值。

    Returns:
        更新後的 payload。
    """
    payload = dict(raw) if isinstance(raw, dict) else {}
    payload["stale_revalidation_failures"] = "0"
    payload["last_revalidation_failed_at_epoch_ms"] = "0"
    payload["next_retry_not_before_epoch_ms"] = "0"
    project_id = str(payload.get("project_id", "") or "").strip()
    slug = str(payload.get("slug", "") or "").strip()
    payload["lifecycle_state"] = PROVIDER_LIFECYCLE_FRESH if project_id or slug else PROVIDER_LIFECYCLE_MISSING
    if project_id or slug:
        resolved_at = int(now_epoch_ms if now_epoch_ms is not None else time.time() * 1000)
        payload["resolved_at_epoch_ms"] = str(resolved_at)
    return payload


def derive_provider_lifecycle_state(
    raw: dict[str, Any] | None, *, ttl_seconds: int = PROVIDER_METADATA_TTL_SECONDS
) -> str:
    """依索引快取內容推導 provider metadata lifecycle state。

    Args:
        raw: 原始 provider metadata。
        ttl_seconds: 視為新鮮的存活秒數。

    Returns:
        推導後的 lifecycle state。

    回傳值為 ``PROVIDER_LIFECYCLE_*`` 常數之一：
    - ``"fresh"``   ─ 快取存在且在 TTL 視窗內
    - ``"stale"``   ─ 快取存在但已超過 TTL
    - ``"missing"`` ─ 快取不存在或無 project_id/slug
    """
    if not isinstance(raw, dict) or not raw:
        return PROVIDER_LIFECYCLE_MISSING
    project_id = str(raw.get("project_id", "") or "").strip()
    slug = str(raw.get("slug", "") or "").strip()
    if not project_id and (not slug):
        return PROVIDER_LIFECYCLE_MISSING
    lifecycle_override = str(raw.get("lifecycle_state", "") or "").strip().lower()
    if lifecycle_override in {PROVIDER_LIFECYCLE_RETRYING, PROVIDER_LIFECYCLE_INVALIDATED} and (
        not is_provider_revalidation_retry_due(raw)
    ):
        return lifecycle_override
    if is_cached_provider_metadata_fresh(raw, ttl_seconds=ttl_seconds):
        return PROVIDER_LIFECYCLE_FRESH
    return PROVIDER_LIFECYCLE_STALE


def cache_provider_metadata_record(
    index_manager: Any,
    file_path: str | Path,
    provider_metadata: ProviderMetadataRecord,
    *,
    metadata_source: str | None = None,
    resolved_at_epoch_ms: int | None = None,
) -> None:
    """使用統一 contract 將 provider metadata 寫回索引。

    Args:
        index_manager: 索引管理器。
        file_path: 原始檔案路徑。
        provider_metadata: 要寫回的 provider metadata。
        metadata_source: 資料來源標記。
        resolved_at_epoch_ms: 已解析時間毫秒值。
    """
    normalized_path = Path(file_path)
    payload = provider_metadata.as_cache_payload()
    normalized_source = str(metadata_source or "").strip().lower()
    if normalized_source:
        payload["resolution_source"] = normalized_source
        resolved_ts = resolved_at_epoch_ms if resolved_at_epoch_ms is not None else int(time.time() * 1000)
        payload["resolved_at_epoch_ms"] = str(int(resolved_ts))
    index_manager.cache_provider_metadata(normalized_path, payload)
