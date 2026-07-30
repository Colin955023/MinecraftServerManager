"""
Loader Adapter 工具函式。
提供 Forge 與 NeoForge 共用的 Maven XML 解析邏輯。
"""

import re

from defusedxml import ElementTree as ET

from ...utils import get_logger

logger = get_logger().bind(component="LoaderAdapterUtils")


class MavenMetadataParser:
    """Maven metadata XML 解析器，提供 Forge / NeoForge 共用的版本解析邏輯。"""

    @staticmethod
    def extract_stable_version_strings(content: bytes) -> list[str]:
        """
        從 Maven metadata XML 中提取穩定版本字串，排除 pre-release / beta / alpha / snapshot / rc。

        Args:
            content: Maven metadata XML 內容位元組。

        Returns:
            符合條件的版本字串列表。
        """
        root = ET.fromstring(content)
        versions: list[str] = []
        for version_elem in root.findall(".//version"):
            version_text = version_elem.text
            if version_text and "-" in version_text:
                lower_text = version_text.lower()
                test_keywords = ["pre", "prelease", "beta", "alpha", "snapshot", "rc"]
                if any(keyword in lower_text for keyword in test_keywords):
                    continue
                versions.append(version_text.strip())
        return versions

    @staticmethod
    def extract_all_version_strings(content: bytes) -> list[str]:
        """
        從 Maven metadata XML 中提取所有版本字串（包含 pre-release）。

        Args:
            content: Maven metadata XML 內容位元組。

        Returns:
            所有解析出的版本字串列表。
        """
        root = ET.fromstring(content)
        versions: list[str] = []
        for version_elem in root.findall(".//version"):
            version_text = version_elem.text
            if version_text:
                versions.append(version_text.strip())
        return versions

    @staticmethod
    def normalize_version_strings(versions: list[str]) -> list[str]:
        """
        將原始版本字串正規化為統一的 ``{mc_version}-{loader_version}`` 格式。

        Args:
            versions: 原始版本字串列表。

        Returns:
            正規化後的版本字串列表。
        """
        normalized_versions: list[str] = []
        for version in versions:
            if "-" in version:
                parts = version.split("-", 1)
                mc_part = parts[0]
                suffix_part = parts[1]

                mc_clean = re.sub(r"[^0-9.]", "", mc_part).rstrip(".")
                suffix_clean = re.sub(r"[^0-9.]", "", suffix_part).rstrip(".")
                mc_parts = [part for part in mc_clean.split(".") if part]

                suffix_text = suffix_part.strip().rstrip(".")

                if mc_clean and suffix_clean and mc_parts and mc_parts[0] == "1" and len(mc_parts) <= 3:
                    normalized_versions.append(f"{mc_clean}-{suffix_text}")
                elif mc_clean and len(mc_parts) > 3:
                    mc_rejoined = ".".join(mc_parts[:3])
                    suffix_rejoined = ".".join(mc_parts[3:]) + "-" + suffix_text
                    normalized_versions.append(f"{mc_rejoined}-{suffix_rejoined}")
            else:
                version_clean = re.sub(r"[^0-9.]", "", version).rstrip(".")
                if version_clean:
                    parts = version_clean.split(".")
                    if len(parts) >= 6 and parts[0] == "1":
                        normalized_versions.append(f"{'.'.join(parts[:3])}-{'.'.join(parts[3:])}")
                    elif len(parts) >= 3 and parts[0] in {"20", "21"}:
                        normalized_versions.append(f"1.{parts[0]}.{parts[1]}-{version_clean}")
                    elif len(parts) >= 3:
                        mc_version = f"{parts[0]}.{parts[1]}"
                        loader_version = parts[-1]
                        normalized_versions.append(f"{mc_version}-{loader_version}")
                    elif len(parts) == 2:
                        normalized_versions.append(version_clean)
        return normalized_versions

    @staticmethod
    def build_version_dict_from_strings(filtered_versions: list[str]) -> dict[str, list[str]]:
        """
        將正規化後的版本字串列表轉為 ``{mc_version: [full_version, ...]}`` 字典。

        Args:
            filtered_versions: 已經過濾並正規化的版本字串列表。

        Returns:
            依照 Minecraft 版本分類的載入器版本字典。
        """
        version_dict: dict[str, list[str]] = {}
        for version in filtered_versions:
            if "-" in version:
                try:
                    parts = version.split("-", 1)
                    if len(parts) == 2:
                        mc_version = parts[0]
                        mc_parts = mc_version.split(".")
                        if len(mc_parts) == 4:
                            mc_version = ".".join(mc_parts[:3])
                        if mc_version not in version_dict:
                            version_dict[mc_version] = []
                        version_dict[mc_version].append(version)
                except (ValueError, IndexError) as e:
                    logger.debug(f"解析版本字串失敗 '{version}': {e}")
                    continue
        return version_dict

    @classmethod
    def build_loader_version_dict_from_metadata(
        cls, content: bytes, allow_prerelease: bool = False
    ) -> dict[str, list[str]]:
        """從 Maven metadata XML 內容建立載入器版本字典的完整流程。

        Args:
            content: Maven metadata XML 的原始位元組內容。
            allow_prerelease: 是否包含 pre-release 版本（NeoForge 設為 True）。

        Returns:
            ``{mc_version: [full_version_string, ...]}`` 格式的版本字典。
        """
        if allow_prerelease:
            versions = cls.extract_all_version_strings(content)
        else:
            versions = cls.extract_stable_version_strings(content)
        normalized_versions = cls.normalize_version_strings(versions)
        if not normalized_versions:
            return {}
        return cls.build_version_dict_from_strings(normalized_versions)

    @staticmethod
    def parse_forge_version_tuple(version_text: str) -> tuple[int, ...]:
        """
        將 Forge / NeoForge 版本字串解析為數值 tuple，用於排序比較。

        Args:
            version_text: 載入器版本字串。

        Returns:
            代表版本的數值 tuple。
        """
        numeric_parts = re.findall(r"\d+", str(version_text or ""))
        if not numeric_parts:
            return (0,)
        return tuple(int(p) for p in numeric_parts)


def build_standard_installer_args(
    java_path: str, installer_path: str, _minecraft_version: str, _loader_version: str, _download_dir: str
) -> list[str]:
    """
    Forge / NeoForge 共用的標準安裝器命令列參數。

    Args:
        java_path: Java 執行檔路徑。
        installer_path: 安裝器 jar 檔案路徑。
        _minecraft_version: Minecraft 遊戲版本。
        _loader_version: 載入器版本。
        _download_dir: 下載目錄。

    Returns:
        包含安裝指令參數的字串列表。
    """
    return [java_path, "-jar", installer_path, "--installServer"]
