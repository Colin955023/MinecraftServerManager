"""Modrinth provider catalog adapter；只負責 transport 與 response mapping"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from src.models import CatalogOutcomeKind, ProviderCatalogOutcome
from src.utils import HTTPClient

from .mod_search_constants import (
    MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS,
    MODRINTH_SEARCH_TIMEOUT_SECONDS,
    MODRINTH_SEARCH_URL,
)

MODRINTH_PROJECT_DETAIL_URL = "https://api.modrinth.com/v2/project/{identifier}"


class ModrinthProviderAdapter:
    """將 Modrinth HTTP 結果轉成 provider-neutral typed outcome"""

    def lookup(self, identifier: str) -> ProviderCatalogOutcome:
        """
        以專案 ID 或 slug 查詢單一 Modrinth 專案

        Args:
            identifier: Modrinth 專案 ID 或 slug

        Returns:
            已映射為 provider-neutral 類型的查詢結果
        """
        clean_identifier = str(identifier or "").strip()
        if not clean_identifier:
            return ProviderCatalogOutcome("invalid_response")
        response = HTTPClient.fetch_json_response(
            MODRINTH_PROJECT_DETAIL_URL.format(identifier=quote(clean_identifier, safe="")),
            timeout=MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS,
        )
        if response.error_kind:
            return ProviderCatalogOutcome(self._map_error(response.error_kind))
        if not isinstance(response.payload, dict):
            return ProviderCatalogOutcome("invalid_response")
        return self._map_project(response.payload, confidence=100)

    def search(self, query: str) -> ProviderCatalogOutcome:
        """
        以別名搜尋最相符的 Modrinth 專案

        Args:
            query: 要搜尋的專案名稱或別名

        Returns:
            已評分並映射的搜尋結果
        """
        clean_query = str(query or "").strip()
        if not clean_query:
            return ProviderCatalogOutcome("invalid_response")
        response = HTTPClient.fetch_json_response(
            MODRINTH_SEARCH_URL,
            timeout=MODRINTH_SEARCH_TIMEOUT_SECONDS,
            params={"query": clean_query, "limit": 8, "facets": '[["project_type:mod"]]'},
        )
        if response.error_kind:
            return ProviderCatalogOutcome(self._map_error(response.error_kind))
        if not isinstance(response.payload, dict):
            return ProviderCatalogOutcome("invalid_response")
        hits = response.payload.get("hits")
        if not isinstance(hits, list) or not hits:
            return ProviderCatalogOutcome("not_found")
        candidate_keys = {_key(clean_query)}
        best: tuple[int, dict[str, Any]] | None = None
        for raw_hit in hits:
            if not isinstance(raw_hit, dict):
                continue
            hit_keys = {
                _key(raw_hit.get("project_id")),
                _key(raw_hit.get("slug")),
                _key(raw_hit.get("title") or raw_hit.get("name")),
            }
            hit_keys.discard("")
            score = 100 if candidate_keys & hit_keys else 70 if _partially_matches(candidate_keys, hit_keys) else 10
            if best is None or score > best[0]:
                best = (score, raw_hit)
        if best is None:
            return ProviderCatalogOutcome("invalid_response")
        return self._map_project(best[1], confidence=best[0])

    @staticmethod
    def _map_project(raw: dict[str, Any], *, confidence: int) -> ProviderCatalogOutcome:
        project_id = str(raw.get("id", raw.get("project_id", "")) or "").strip()
        if not project_id:
            return ProviderCatalogOutcome("invalid_response")
        return ProviderCatalogOutcome(
            "found",
            provider="modrinth",
            project_id=project_id,
            alias=str(raw.get("slug", "") or "").strip(),
            display_name=str(raw.get("title", raw.get("name", "")) or "").strip(),
            confidence=confidence,
        )

    @staticmethod
    def _map_error(error_kind: str) -> CatalogOutcomeKind:
        if error_kind == "not_found":
            return "not_found"
        if error_kind == "rate_limited":
            return "rate_limited"
        if error_kind in {"timeout", "transient"}:
            return "transient_failure"
        return "invalid_response"


def _key(value: Any) -> str:
    return "".join(character for character in str(value or "").strip().lower() if character.isalnum())


def _partially_matches(left: set[str], right: set[str]) -> bool:
    return any(a and b and (a in b or b in a) for a in left for b in right)


__all__ = ["ModrinthProviderAdapter"]
