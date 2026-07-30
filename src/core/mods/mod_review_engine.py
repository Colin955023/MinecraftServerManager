"""
模組審查引擎。
處理模組版本相容性判斷、依賴驗證、排序等領域邏輯，與 UI 完全解耦。
"""

from typing import Any


class VersionReviewEngine:
    """負責執行版本相容性驗證與排序邏輯。"""

    @staticmethod
    def _normalize_online_version_type(value: Any) -> str:
        """正規化版本類型，避免不同 provider 字串差異造成排序飄移。"""
        return str(value or "").strip().lower()

    @classmethod
    def get_online_version_type_rank(cls, version_type: Any) -> int:
        """回傳版本穩定度排名（數字越小越優先）。"""
        normalized = cls._normalize_online_version_type(version_type)
        if normalized in {"release", "stable"}:
            return 0
        if normalized in {"beta", "pre", "preview", "rc"}:
            return 1
        if normalized in {"alpha", "snapshot"}:
            return 2
        return 3

    @staticmethod
    def get_online_version_compatibility_rank(report: Any | None) -> int:
        """相容性排名（數字越小越優先）。"""
        if report is None:
            return 1
        return 0 if bool(getattr(report, "compatible", True)) else 2

    @classmethod
    def sort_online_versions_for_server(
        cls, versions: list[Any], version_reports: list[Any] | None
    ) -> tuple[list[Any], list[Any] | None]:
        """
        伺服器安裝場景排序：相容性 > 穩定度 > 發布時間。

        Args:
            versions: 版本列表。
            version_reports: 版本報告列表。
        Returns:
            排序後的版本列表與對應報告列表。
        """
        if not versions:
            return (versions, version_reports)

        indexed_reports: list[Any | None]
        if version_reports is None:
            indexed_reports = [None] * len(versions)
        else:
            indexed_reports = [
                version_reports[index] if index < len(version_reports) else None for index in range(len(versions))
            ]

        merged = list(zip(versions, indexed_reports, strict=False))

        def _published_sort_value(version: Any) -> tuple[int, str]:
            published = str(getattr(version, "date_published", "") or "")
            return (0 if published else 1, published)

        merged.sort(
            key=lambda item: (
                cls.get_online_version_compatibility_rank(item[1]),
                cls.get_online_version_type_rank(getattr(item[0], "version_type", "")),
                _published_sort_value(item[0]),
            )
        )

        grouped: dict[tuple[int, int], list[tuple[Any, Any | None]]] = {}
        for row in merged:
            group_key = (
                cls.get_online_version_compatibility_rank(row[1]),
                cls.get_online_version_type_rank(getattr(row[0], "version_type", "")),
            )
            grouped.setdefault(group_key, []).append(row)

        merged = []
        for group_key in sorted(grouped):
            group_rows = grouped[group_key]
            group_rows.sort(key=lambda row: str(getattr(row[0], "date_published", "") or ""), reverse=True)
            merged.extend(group_rows)

        sorted_versions = [item[0] for item in merged]
        if version_reports is None:
            return (sorted_versions, None)

        sorted_reports = [item[1] for item in merged]
        return (sorted_versions, sorted_reports)

    @staticmethod
    def get_online_version_status_text(report: Any | None) -> str:
        """
        將版本分析結果轉成簡短狀態，供列表快速判讀。

        Args:
            report: 版本分析報告。
        Returns:
            簡短狀態文字。
        """
        if report is None:
            return "未分析"
        if not getattr(report, "compatible", True):
            return "不相容"
        if list(getattr(report, "missing_required_dependencies", []) or []):
            return "可安裝，含依賴"
        if list(getattr(report, "incompatible_installed", []) or []) or list(
            getattr(report, "installed_version_mismatches", []) or []
        ):
            return "可安裝，需注意"
        if list(getattr(report, "warnings", []) or []):
            return "可安裝，需注意"
        return "可安裝"
