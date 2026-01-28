#!/usr/bin/env python3
"""
模組管理器
負責管理 Minecraft 伺服器的模組，提供下載、更新、啟用/停用、移除等功能
Mod Manager Module
Responsible for managing Minecraft server mods with downloading, updating, enabling/disabling, removing capabilities
"""

import json
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import toml

from ..utils import HTTPUtils, UIUtils, get_logger
from ..version_info import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

logger = get_logger().bind(component="ModManager")


# ====== 模組狀態與平台定義 ======
class ModStatus(Enum):
    """
    模組狀態列舉，定義模組的各種狀態
    Mod status enumeration defining various mod states
    """

    ENABLED = "enabled"
    DISABLED = "disabled"


class ModPlatform(Enum):
    """
    模組來源平台列舉，定義模組的來源平台
    Mod source platform enumeration defining mod source platforms
    """

    MODRINTH = "modrinth"
    LOCAL = "local"


@dataclass
class LocalModInfo:
    """
    本地模組資訊資料類別
    Data class for local mod information.
    """

    id: str
    name: str
    filename: str
    version: str
    minecraft_version: str
    loader_type: str
    description: str = ""
    author: str = ""
    platform: ModPlatform = ModPlatform.LOCAL
    platform_id: str = ""
    status: ModStatus = ModStatus.ENABLED
    file_path: str = ""
    download_url: str = ""
    homepage_url: str = ""
    dependencies: list[str] | None = None
    file_size: int = 0

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


# ====== 模組管理器主類別 ======
class ModManager:
    """
    模組管理器類別，負責伺服器模組的掃描、啟用/停用、下載、更新和依賴管理
    Mod manager class responsible for scanning, enabling/disabling, downloading, updating and dependency management of server mods
    """

    # ====== 初始化與設定 ======
    # 初始化模組管理器
    def __init__(self, server_path: str, server_config=None):
        """
        初始化模組管理器
        Initialize mod manager

        Args:
            server_path (str): 伺服器路徑
            server_config: 伺服器配置物件

        Returns:
            None
        """
        self.server_path = Path(server_path)
        self.mods_path = self.server_path / "mods"
        self.server_config = server_config  # 儲存伺服器配置

        # 確保目錄存在
        self.mods_path.mkdir(exist_ok=True)
        # 回調函數
        self.on_mod_list_changed: Callable | None = None

    # ====== 模組掃描與檔案管理 ======
    # 掃描 mods 目錄中的模組檔案
    def scan_mods(self) -> list[LocalModInfo]:
        """
        掃描 mods 目錄中的模組檔案並建立模組資訊列表（多執行緒優化，I/O 密集型任務）
        Scan mod files in the mods directory and create mod information list (multithreaded optimization for I/O-bound tasks)

        Args:
            None

        Returns:
            List[LocalModInfo]: 模組資訊列表
        """
        mods = []
        files_to_scan = []

        # 掃描 .jar 和 .jar.disabled 檔案
        for file_path in self.mods_path.glob("*.jar*"):
            if file_path.suffix == ".jar" or file_path.name.endswith(".jar.disabled"):
                files_to_scan.append(file_path)

        # 使用 ThreadPoolExecutor 並行處理（JAR 檔案讀取主要是 I/O 操作）
        # 每個 worker 獨立處理檔案，避免 GIL 影響
        with ThreadPoolExecutor(max_workers=min(10, len(files_to_scan) or 1)) as executor:
            results = executor.map(self.create_mod_info_from_file, files_to_scan)

        for mod_info in results:
            if mod_info:
                mods.append(mod_info)

        return mods

    def create_mod_info_from_file(self, file_path: Path) -> LocalModInfo | None:
        """
        依 Prism Launcher 行為，從 jar metadata 取得版本，支援 fallback 與多格式
        Create mod information from a file, extracting metadata and applying fallback logic

        Args:
            file_path (Path): 檔案路徑

        Returns:
            LocalModInfo | None: 本地模組資訊物件
        """
        try:
            # 解析基本檔案資訊
            filename, enabled, base_name = self._parse_file_info(file_path)

            # 初始化模組資料字典
            mod_data = {
                "name": base_name,
                "version": "未知",
                "author": "",
                "description": "",
                "loader_type": "未知",
                "mc_version": "未知",
            }

            # 從 jar 檔案提取元資料
            self._extract_metadata_from_jar(file_path, mod_data)

            # 套用後備邏輯與清理
            self._apply_fallback_logic(base_name, mod_data)

            # 套用伺服器設定覆寫
            self._apply_server_config_overrides(mod_data)

            # 偵測平台資訊
            platform, platform_id = self._detect_platform_info(file_path, mod_data["name"], base_name, filename)
            return LocalModInfo(
                id=base_name,
                name=mod_data["name"],
                filename=filename,
                version=mod_data["version"],
                minecraft_version=mod_data["mc_version"],
                loader_type=mod_data["loader_type"],
                description=mod_data["description"],
                author=mod_data["author"],
                platform=platform,
                platform_id=platform_id,
                status=ModStatus.ENABLED if enabled else ModStatus.DISABLED,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
            )
        except Exception as e:
            logger.error(f"解析模組檔案失敗 {file_path}: {e}", "ModManager")
            return None

    def _parse_file_info(self, file_path: Path) -> tuple[str, bool, str]:
        """
        解析基本檔案資訊與啟用/停用狀態
        Extract basic file information and enabled/disabled status

        Args:
            file_path (Path): 檔案路徑

        Returns:
            tuple[str, bool, str]: 檔案名稱、啟用狀態、基本名稱
        """
        filename = file_path.name
        # 使用 removesuffix (Python 3.9+) 更簡潔
        enabled = not filename.endswith(".jar.disabled")
        base_name = filename.removesuffix(".jar.disabled").removesuffix(".jar")
        return filename, enabled, base_name

    def _get_manifest_version(self, jar) -> str | None:
        """
        從 MANIFEST.MF 檔案中提取版本資訊
        get the version information from the MANIFEST.MF file

        Args:
            jar: zipfile.ZipFile 物件

        Returns:
            str | None: 版本資訊字串
        """
        try:
            if "META-INF/MANIFEST.MF" in jar.namelist():
                with jar.open("META-INF/MANIFEST.MF") as mf:
                    for line in mf.read().decode(errors="ignore").splitlines():
                        if line.startswith("Implementation-Version:"):
                            v = line.split(":", 1)[1].strip()
                            if v and v != "${projectversion}":
                                return v
        except Exception as e:
            logger.exception(f"讀取 MANIFEST.MF 版本資訊失敗: {e}")
        return None

    def _extract_metadata_from_jar(self, file_path: Path, mod_data: dict) -> None:
        """
        根據模組載入器類型從 jar 檔案中提取元資料（統一處理邏輯）
        Extract metadata from jar file according to mod loader type (unified processing logic)

        Args:
            file_path (Path): 檔案路徑
            mod_data (dict): 模組元資料字典
        """
        try:
            with zipfile.ZipFile(file_path, "r") as jar:
                # 根據檔案存在判斷模組類型並提取元資料
                metadata_extractors = [
                    ("fabric.mod.json", self._extract_fabric_metadata),
                    ("META-INF/mods.toml", self._extract_forge_metadata),
                    ("mcmod.info", self._extract_legacy_forge_metadata),
                ]

                jar_files = jar.namelist()
                for metadata_file, extractor in metadata_extractors:
                    if metadata_file in jar_files:
                        extractor(jar, mod_data)
                        break  # 找到第一個匹配的元資料檔案即停止
        except Exception as e:
            logger.exception(f"從 JAR 提取元資料失敗 {file_path}: {e}")

    def _extract_fabric_metadata(self, jar, mod_data: dict) -> None:
        """
        從 Fabric 模組中提取元資料
        extract metadata from Fabric mod

        Args:
            jar: zipfile.ZipFile 物件
        """
        try:
            with jar.open("fabric.mod.json") as f:
                meta = json.load(f)

            mod_data["name"] = meta.get("name", mod_data["name"])
            mod_data["version"] = self._resolve_version(jar, meta.get("version", mod_data["version"]))
            mod_data["description"] = meta.get("description", mod_data["description"])
            mod_data["author"] = self._process_authors(meta.get("authors", []))
            mod_data["loader_type"] = "Fabric"

            depends = meta.get("depends", {})
            if isinstance(depends, dict):
                mc_version = depends.get("minecraft", mod_data["mc_version"])
                mod_data["mc_version"] = self._normalize_mc_version(mc_version)
        except (TypeError, Exception) as e:
            logger.error(f"無法從 JAR 檔案提取 Fabric 元資料: {e}", "ModManager")

    def _extract_forge_metadata(self, jar, mod_data: dict) -> None:
        """
        從 Forge 模組中提取元資料
        extract metadata from Forge mod

        Args:
            jar: zipfile.ZipFile 物件
            mod_data (dict): 模組元資料字典
        """
        try:
            with jar.open("META-INF/mods.toml") as f:
                toml_txt = f.read().decode(errors="ignore")
                meta = toml.loads(toml_txt)

            modlist = meta.get("mods", [])
            if modlist and isinstance(modlist, list):
                modmeta = modlist[0]
                mod_data["name"] = modmeta.get("displayName", mod_data["name"])
                mod_data["version"] = self._resolve_version(jar, modmeta.get("version", mod_data["version"]))
                mod_data["description"] = modmeta.get("description", mod_data["description"])
                mod_data["author"] = self._process_authors(modmeta.get("authors", mod_data["author"]))

            mod_data["loader_type"] = "Forge"

            if "dependencies" in meta:
                for dep in meta["dependencies"].values():
                    if isinstance(dep, list):
                        for d in dep:
                            if d.get("modId") == "minecraft":
                                mc_version = d.get("versionRange", mod_data["mc_version"])
                                mod_data["mc_version"] = self._normalize_mc_version(mc_version)
                                break
        except Exception as e:
            logger.exception(f"解析 Forge 元資料失敗: {e}")

    def _extract_legacy_forge_metadata(self, jar, mod_data: dict) -> None:
        """
        從舊版 Forge 模組（mcmod.info）提取元資料
        extract metadata from legacy Forge mod (mcmod.info)

        Args:
            jar: zipfile.ZipFile 物件
            mod_data (dict): 模組元資料字典
        """
        try:
            with jar.open("mcmod.info") as f:
                info_txt = f.read().decode(errors="ignore")
                info = json.loads(info_txt)

                if isinstance(info, list):
                    info = info[0]

                mod_data["name"] = info.get("name", mod_data["name"])
                mod_data["version"] = info.get("version", mod_data["version"])
                mod_data["description"] = info.get("description", mod_data["description"])

                # Handle authorList or author field
                authors = info.get("authorList") or info.get("author", mod_data["author"])
                mod_data["author"] = self._process_authors(authors)
                mod_data["mc_version"] = info.get("mcversion", mod_data["mc_version"])
                mod_data["loader_type"] = "Forge"
        except Exception as e:
            logger.exception(f"解析 legacy Forge mcmod.info 失敗: {e}")

    def _resolve_version(self, jar, version: str) -> str:
        """
        解析版本號，處理佔位符 ${file.jarVersion}
        Resolve version number, handling placeholder ${file.jarVersion}

        Args:
            jar: zipfile.ZipFile 物件
            version (str): 原始版本字串

        Returns:
            str: 解析後的版本字串
        """
        if version == "${file.jarVersion}":
            manifest_version = self._get_manifest_version(jar)
            return manifest_version if manifest_version else version
        return version

    def _process_authors(self, authors) -> str:
        """
        處理並清理作者資訊
        process and clean author information

        Args:
            authors: 可能是字串或字串列表的作者資訊

        Returns:
            處理後的作者資訊字串
        """
        if isinstance(authors, list) and authors:
            return ", ".join(
                [
                    str(a)
                    for a in authors
                    if a and str(a).strip().lower() not in ["", "unknown", "author", "example author", "example"]
                ],
            )
        if isinstance(authors, str):
            return authors
        return ""

    def _normalize_mc_version(self, mc_version) -> str:
        """
        標準化 Minecraft 版本字串
        normalize Minecraft version string

        Args:
            mc_version: 要標準化的 Minecraft 版本字串

        Returns:
            標準化後的 Minecraft 版本字串
        """
        if isinstance(mc_version, list) and mc_version:
            mc_version = str(mc_version[0])
        if isinstance(mc_version, str) and (mc_version.startswith(("[", "("))):
            m = re.search(r"(\d+\.\d+)", mc_version)
            if m:
                mc_version = m.group(1)
        return mc_version

    def _apply_fallback_logic(self, base_name: str, mod_data: dict) -> None:
        """
        套用後備邏輯來填充模組資料
        Apply fallback logic for missing mod information

        Args:
            base_name: 基礎檔案名稱
            mod_data: 模組資料字典
        """
        # 清理作者資訊
        mod_data["author"] = self._clean_author(mod_data["author"])

        # 從檔名回退提取名稱
        if not mod_data["name"] or mod_data["name"] == "未知":
            mod_data["name"] = self._extract_name_from_filename(base_name)

        # 從檔名回退提取版本
        if not mod_data["version"] or mod_data["version"] == "未知":
            mod_data["version"] = self._extract_version_from_filename(base_name)

        # 從檔名回退提取 Minecraft 版本
        if not mod_data["mc_version"] or str(mod_data["mc_version"]).strip() in [
            "",
            "未知",
        ]:
            mod_data["mc_version"] = self._extract_mc_version_from_filename(base_name)

        # 從檔名回退偵測載入器類型
        if mod_data["loader_type"] == "未知":
            mod_data["loader_type"] = self._detect_loader_from_filename(base_name)

    def _extract_name_from_filename(self, base_name: str) -> str:
        """
        解析檔名以提取模組名稱
        Extract mod name from filename

        Args:
            base_name: 基礎檔案名稱

        Returns:
            提取的模組名稱
        """
        clean_base = base_name
        clean_base = re.sub(
            r"(?i)[-_]?(forge|fabric|litemod|mc\d+\.\d+\.\d+|mc\d+\.\d+)",
            "",
            clean_base,
        )
        clean_base = re.sub(
            r"(?i)[-_]?(api|mod|core|library|lib|addon|additions|compat|integration|essentials|tools|generators|reforged|restored|beta|alpha|snapshot|universal|common|b\d*)$",
            "",
            clean_base,
        )
        clean_base = clean_base.strip("-_")

        parts = clean_base.split("-")
        if len(parts) > 1:
            for i, p in enumerate(parts):
                if any(c.isdigit() for c in p):
                    return "-".join(parts[:i]) if i > 0 else clean_base
            return clean_base
        return clean_base

    def _extract_version_from_filename(self, base_name: str) -> str:
        """
        解析檔名以提取版本
        Extract version from filename

        Args:
            base_name: 基礎檔案名稱

        Returns:
            提取的版本
        """
        parts = base_name.split("-")
        if len(parts) > 1:
            for i, p in enumerate(parts):
                if any(c.isdigit() for c in p):
                    version = "-".join(parts[i:])
                    return self._clean_version(version)
        return "未知"

    def _extract_mc_version_from_filename(self, base_name: str) -> str:
        """
        解析檔名以提取 Minecraft 版本
        Extract Minecraft version from filename

        Args:
            base_name: 基礎檔案名稱

        Returns:
            提取的 Minecraft 版本
        """
        # Try to find mc1.20.1 or 1.20.1 or 1.20
        patterns = [
            r"mc(\d+\.\d+\.\d+)",
            r"(\d+\.\d+\.\d+)",
            r"mc(\d+\.\d+)",
            r"(\d+\.\d+)",
        ]

        for pattern in patterns:
            m = re.search(pattern, base_name, re.IGNORECASE)
            if m:
                return m.group(1)

        return "未知"

    def _detect_loader_from_filename(self, base_name: str) -> str:
        """
        從檔名偵測載入器類型
        Detect loader type from filename

        Args:
            base_name: 基礎檔案名稱

        Returns:
            偵測到的載入器類型
        """
        if re.search(r"forge", base_name, re.IGNORECASE):
            return "Forge"
        if re.search(r"fabric", base_name, re.IGNORECASE):
            return "Fabric"
        return "未知"

    def _apply_server_config_overrides(self, mod_data: dict) -> None:
        """
        套用伺服器配置覆寫
        Apply server configuration overrides

        Args:
            mod_data: 模組資料字典
        """
        if not self.server_config:
            return

        loader_type = getattr(self.server_config, "loader_type", mod_data["loader_type"])
        mc_version_fallback = getattr(self.server_config, "minecraft_version", mod_data["mc_version"])

        # Override mc_version if empty or invalid
        if (
            not mod_data["mc_version"]
            or str(mod_data["mc_version"]).strip() in ["", "未知"]
            or not re.match(r"^\d+\.\d+", str(mod_data["mc_version"]))
        ):
            mod_data["mc_version"] = mc_version_fallback

        # Normalize loader type
        loader_mapping = {
            "unknown": "未知",
            "fabric": "Fabric",
            "forge": "Forge",
            "vanilla": "原版",
        }
        mod_data["loader_type"] = loader_mapping.get(loader_type.lower(), loader_type)

    def _detect_platform_info(
        self,
        file_path: Path,
        name: str,
        base_name: str,
        filename: str,
    ) -> tuple[ModPlatform, str]:
        """
        從檔案路徑、名稱、基礎名稱和檔案名稱中偵測模組的平台和平台 ID
        Detect platform and platform ID for the mod

        Args:
            file_path: 檔案路徑
            name: 模組名稱
            base_name: 基礎名稱
            filename: 檔案名稱

        Returns:
            模組平台和平台 ID 的元組
        """
        platform = ModPlatform.LOCAL
        platform_id = ""

        try:
            with zipfile.ZipFile(file_path, "r") as jar:
                if "fabric.mod.json" in jar.namelist():
                    platform_id = self._extract_platform_id_from_fabric(jar)
                elif "META-INF/mods.toml" in jar.namelist():
                    platform_id = self._extract_platform_id_from_forge(jar)

                if platform_id:
                    platform = ModPlatform.MODRINTH
        except Exception as e:
            logger.exception(f"從 JAR 偵測平台 ID 失敗 {file_path}: {e}")

        # Fallback: search on Modrinth API
        if platform == ModPlatform.LOCAL or not platform_id:
            platform, platform_id = self._search_on_modrinth(name, base_name, filename)

        return platform, platform_id

    def _extract_platform_id_from_fabric(self, jar) -> str:
        """
        解析 Fabric 模組元資料以提取平台 ID
        Extract platform ID from Fabric mod metadata

        Args:
            jar: zipfile.ZipFile 物件
        Returns:
            模組平台 ID
        """
        try:
            with jar.open("fabric.mod.json") as f:
                meta = json.load(f)
            return meta.get("id", "")
        except Exception as e:
            logger.exception(f"解析 fabric.mod.json 取得平台 ID 失敗: {e}")
            return ""

    def _extract_platform_id_from_forge(self, jar) -> str:
        """
        解析 Forge 模組元資料以提取平台 ID
        Extract platform ID from Forge mod metadata

        Args:
            jar: zipfile.ZipFile 物件

        Returns:
            模組平台 ID
        """
        try:
            with jar.open("META-INF/mods.toml") as f:
                toml_txt = f.read().decode(errors="ignore")
                if "modrinth" in toml_txt.lower():
                    m = re.search(
                        r'(modrinth|project_id)\s*=\s*"([^"]+)"',
                        toml_txt,
                        re.IGNORECASE,
                    )
                    if m:
                        return m.group(2)
        except Exception as e:
            logger.exception(f"解析 mods.toml 取得平台 ID 失敗: {e}")
        return ""

    def _search_on_modrinth(self, name: str, base_name: str, filename: str) -> tuple[ModPlatform, str]:
        """
        在 Modrinth API 上搜索模組
        Search for mod on Modrinth API

        Args:
            name: 模組名稱
            base_name: 基礎名稱
            filename: 檔案名稱

        Returns:
            模組平台和平台 ID 的元組
        """
        try:
            search_keywords = []
            if name and name != "未知":
                search_keywords.append(name)
            if base_name and base_name not in search_keywords:
                search_keywords.append(base_name)
            if filename and filename not in search_keywords:
                search_keywords.append(filename)

            for keyword in search_keywords:
                search_url = f"https://api.modrinth.com/v2/search?query={keyword}"
                headers = {
                    "User-Agent": f"MinecraftServerManager/{APP_VERSION} (github.com/{GITHUB_OWNER}/{GITHUB_REPO})",
                }
                data = HTTPUtils.get_json(search_url, timeout=8, headers=headers)

                if data and data.get("hits"):
                    hit = data["hits"][0]
                    return ModPlatform.MODRINTH, hit.get("slug", "")
        except Exception as e:
            logger.exception(f"Modrinth 搜尋失敗: {e}")

        return ModPlatform.LOCAL, ""

    def _clean_version(self, version: str) -> str:
        """
        清理版本字串，移除後綴如 +, -mc, -fabric, -forge, -kotlin 等
        Clean version string

        Args:
            version: 版本字串

        Returns:
            清理後的版本字串
        """
        if not version or version == "未知":
            return version
        # 移除後綴如 +、-mc、-fabric、-forge、-kotlin 等
        v = re.split(
            r"[+]|-mc|-fabric|-forge|-kotlin|-api|-universal|-common|-b[0-9]*|-beta|-alpha|-snapshot",
            version,
            flags=re.IGNORECASE,
        )[0]
        # 移除結尾的非英數字元
        v = re.sub(r"[^\w\d.]+$", "", v)
        return v.strip()

    def _clean_author(self, author: str) -> str:
        """
        清理作者字串
        Clean author string

        Args:
            author: 作者字串

        Returns:
            清理後的作者字串
        """
        if not author:
            return ""
        author = str(author).strip()
        if author.lower() in ["", "unknown", "author", "example author", "example"]:
            return ""
        return author

    def enable_mod(self, mod_id: str) -> bool:
        """
        啟用模組 - 移除 .disabled 後綴
        Enable mod by removing the .disabled suffix.

        Args:
            mod_id: 模組 ID

        Returns:
            是否成功啟用模組
        """
        try:
            disabled_file = self.mods_path / f"{mod_id}.jar.disabled"
            enabled_file = self.mods_path / f"{mod_id}.jar"

            # 已啟用：如果同時存在 .disabled，視為衝突檔案，嘗試清理/備份
            if enabled_file.exists() and not disabled_file.exists():
                return True

            if enabled_file.exists() and disabled_file.exists():
                try:
                    same_size = enabled_file.stat().st_size == disabled_file.stat().st_size
                except Exception:
                    same_size = False
                if same_size:
                    disabled_file.unlink(missing_ok=True)
                    return True
                # 將多餘的 disabled 檔移開，避免下次掃描重複出現
                bak = self.mods_path / f"{mod_id}.disabled.bak"
                if bak.exists():
                    bak = self.mods_path / f"{mod_id}.disabled.{int(time.time())}.bak"
                disabled_file.rename(bak)
                return True

            if disabled_file.exists():
                disabled_file.rename(enabled_file)
                # UI callback 只能在主執行緒呼叫，避免背景執行緒造成 UI 卡死
                if self.on_mod_list_changed and threading.current_thread() is threading.main_thread():
                    self.on_mod_list_changed()
                return True
            return False
        except Exception as e:
            logger.error(f"啟用模組失敗: {e}", "ModManager")
            if threading.current_thread() is threading.main_thread():
                UIUtils.show_error("啟用失敗", f"啟用模組失敗: {e}")
            return False

    def disable_mod(self, mod_id: str) -> bool:
        """
        停用模組 - 添加 .disabled 後綴
        Disable mod by adding the .disabled suffix.

        Args:
            mod_id: 模組 ID

        Returns:
            是否成功停用模組
        """
        try:
            enabled_file = self.mods_path / f"{mod_id}.jar"
            disabled_file = self.mods_path / f"{mod_id}.jar.disabled"

            # 已停用：如果同時存在 .jar，視為衝突檔案，嘗試清理/備份
            if disabled_file.exists() and not enabled_file.exists():
                return True

            if disabled_file.exists() and enabled_file.exists():
                try:
                    same_size = enabled_file.stat().st_size == disabled_file.stat().st_size
                except Exception:
                    same_size = False
                if same_size:
                    enabled_file.unlink(missing_ok=True)
                    return True
                # 將多餘的 enabled 檔移開，避免下次掃描重複出現
                bak = self.mods_path / f"{mod_id}.enabled.bak"
                if bak.exists():
                    bak = self.mods_path / f"{mod_id}.enabled.{int(time.time())}.bak"
                enabled_file.rename(bak)
                return True

            if enabled_file.exists():
                enabled_file.rename(disabled_file)
                # UI callback 只能在主執行緒呼叫，避免背景執行緒造成 UI 卡死
                if self.on_mod_list_changed and threading.current_thread() is threading.main_thread():
                    self.on_mod_list_changed()
                return True
            return False
        except Exception as e:
            logger.error(f"停用模組失敗: {e}", "ModManager")
            if threading.current_thread() is threading.main_thread():
                UIUtils.show_error("停用失敗", f"停用模組失敗: {e}")
            return False

    def get_mod_list(self, include_disabled: bool = True) -> list[LocalModInfo]:
        """
        獲取模組列表
        Get mod list, optionally including disabled mods.

        Args:
            include_disabled: 是否包含已停用的模組

        Returns:
            模組列表
        """
        mods = self.scan_mods()  # 即時掃描

        if include_disabled:
            return mods
        return [mod for mod in mods if mod.status == ModStatus.ENABLED]

    def export_mod_list(self, format_type: str = "text") -> str:
        """
        匯出模組列表
        支援 text/json/html
        Export the mod list.
        support text/json/html

        Args:
            format_type: 匯出格式類型

        Returns:
            匯出結果
        """
        mods = self.get_mod_list()
        if format_type == "text":
            lines = ["# 模組列表", ""]
            for mod in mods:
                status_icon = "✅" if mod.status == ModStatus.ENABLED else "❌"
                line = f"{status_icon} {mod.name} ({mod.version})"
                if mod.author:
                    line += f" - by {mod.author}"
                lines.append(line)
            return "\n".join(lines)
        if format_type == "json":
            export_data = []
            for mod in mods:
                export_data.append(
                    {
                        "name": mod.name,
                        "version": mod.version,
                        "enabled": mod.status == ModStatus.ENABLED,
                        "author": mod.author,
                        "filename": mod.filename,
                        "description": mod.description,
                        "id": mod.id,
                    }
                )
            return json.dumps(export_data, ensure_ascii=False, indent=2)
        if format_type == "html":
            html = [
                "<!DOCTYPE html>",
                '<html lang="zh-TW">',
                '<head><meta charset="UTF-8"><title>模組列表</title>',
                "<style>table{border-collapse:collapse;}th,td{border:1px solid #ccc;padding:6px;}th{background:#f1f5f9;}</style>",
                "</head><body>",
                "<h2>模組列表</h2>",
                "<table>",
                "<tr><th>啟用</th><th>名稱</th><th>版本</th><th>作者</th><th>描述</th></tr>",
            ]
            for mod in mods:
                html.append(
                    "<tr>"
                    f"<td>{'✅' if mod.status == ModStatus.ENABLED else '❌'}</td>"
                    f"<td>{mod.name}</td>"
                    f"<td>{mod.version}</td>"
                    f"<td>{mod.author}</td>"
                    f"<td>{mod.description}</td>"
                    "</tr>",
                )
            html.append("</table></body></html>")
            return "\n".join(html)
        return ""
