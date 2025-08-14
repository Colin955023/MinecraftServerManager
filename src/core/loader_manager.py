#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模組載入器管理器
負責處理 Fabric、Forge 載入器的版本管理與下載，支援自動取得最新版本資訊並提供相容性檢查
Loader Manager Module
Responsible for managing and downloading versions of Fabric and Forge loaders with automatic version retrieval and compatibility checks
"""
# ====== 標準函式庫 ======
from contextlib import suppress
from pathlib import Path
from typing import List, Optional, Union
import json
import os
import re
import subprocess
from lxml import etree
# ====== 專案內部模組 ======
from src.models import LoaderVersion
from src.utils import java_utils
from src.utils.http_utils import HTTPUtils
from src.utils.runtime_paths import ensure_dir, get_cache_dir
from src.utils.log_utils import LogUtils
from src.utils.ui_utils import UIUtils

class LoaderManager:
    """
    模組載入器管理器類別，管理 Fabric 和 Forge 載入器版本
    Loader Manager class for managing Fabric and Forge loader versions
    """

    # ====== 初始化與快取管理 ======

    # 初始化載入器管理器
    def __init__(self):
        """
        初始化載入器管理器
        Initialize loader manager
        
        Args:
            None
            
        Returns:
            None
        """
        cache_dir = ensure_dir(get_cache_dir())
        self.fabric_cache_file = str(cache_dir / "fabric_versions_cache.json")
        self.forge_cache_file = str(cache_dir / "forge_versions_cache.json")

    # 清除 Fabric 快取檔案
    def clear_fabric_cache(self, parent=None):
        """
        清除 Fabric 快取檔案
        Clear Fabric cache file
        
        Args:
            parent (Optional[tk.Toplevel]): 父視窗，若為 None則不顯示對話框

        Returns:
            None
        """
        self._clear_cache_file(self.fabric_cache_file, parent=parent)

    def clear_forge_cache(self, parent=None):
        """清除 Forge 快取檔案。"""
        self._clear_cache_file(self.forge_cache_file, parent=parent)

    def _clear_cache_file(self, cache_file: str, parent=None):
        """通用快取檔案清除方法。"""
        try:
            os.remove(cache_file)
        except PermissionError as e:
            UIUtils.show_error("清除快取檔案失敗", f"無法刪除快取檔案: {cache_file}\n權限不足\n{e}", parent=parent)
        except Exception as e:
            UIUtils.show_error("清除快取檔案失敗", f"無法刪除快取檔案: {cache_file}\n{e}", parent=parent)

    # ======== 公開 API ========

    def download_server_jar_with_progress(
        self,
        loader_type: str,
        minecraft_version: str,
        loader_version: str,
        download_path: str,
        progress_callback=None,
        cancel_flag: Optional[dict] = None,
        user_java_path: Optional[str] = None,
        parent_window=None
    ) -> Union[bool, str]:
        """
        依 loader_type 下載並部署伺服器檔案。
        Vanila/Fabric → bool；Forge → 成功時回傳主 JAR 相對路徑字串。
        """
        lt = self._standardize_loader_type(loader_type, loader_version)

        # 1. 取得 Java 執行檔路徑
        if user_java_path and os.path.exists(user_java_path):
            java_path = user_java_path
        else:
            java_path = java_utils.get_best_java_path(minecraft_version, loader_type, loader_version, parent=parent_window)
        if not java_path:
            return False

        # 2. 依不同載入器執行
        if lt == "vanilla":
            return self._download_vanilla_server(minecraft_version, download_path, progress_callback, cancel_flag)

        if lt == "fabric":
            return self._download_and_run_installer(
                installer_url="https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.0.3/fabric-installer-1.0.3.jar",
                installer_args=[
                    java_path,
                    "-jar",
                    "{installer}",
                    "server",
                    "-mcversion",
                    minecraft_version,
                    "-loader",
                    loader_version,
                    "-dir",
                    os.path.dirname(download_path),
                ],
                minecraft_version=minecraft_version,
                loader_version=loader_version,
                download_path=download_path,
                progress_callback=progress_callback,
                cancel_flag=cancel_flag,
                post_msg="Fabric 伺服器安裝完成",
                need_vanilla=True,
                parent_window=parent_window
            )

        if lt == "forge":
            installer_url = (
                "https://maven.minecraftforge.net/net/minecraftforge/forge/"
                f"{minecraft_version}-{loader_version}/"
                f"forge-{minecraft_version}-{loader_version}-installer.jar"
            )
            result = self._download_and_run_installer(
                installer_url=installer_url,
                installer_args=[
                    java_path,
                    "-jar",
                    "{installer}",
                    "--installServer",
                ],
                minecraft_version=minecraft_version,
                loader_version=loader_version,
                download_path=download_path,
                progress_callback=progress_callback,
                cancel_flag=cancel_flag,
                post_msg="Forge 伺服器安裝完成",
                need_vanilla=False,
                parent_window=parent_window
            )
            return result  # may be str (主 JAR 相對路徑)

        return self._fail(
            progress_callback,
            f"未知的載入器類型: {loader_type}",
            debug=f"[DEBUG] Unknown loader_type={loader_type}",
        )

    def preload_fabric_versions(self, parent=None):
        """從 API 取得所有 Fabric 載入器版本並覆蓋寫入 json。"""
        url = "https://meta.fabricmc.net/v2/versions/loader"
        try:
            data = HTTPUtils.get_json(url, timeout=15)
            if data:
                with open(self.fabric_cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            LogUtils.debug(f"載入 Fabric 版本失敗: {e}", "LoaderManager")
            UIUtils.show_error("載入 Fabric 版本失敗", f"無法從 API 獲取 Fabric 版本：{e}", parent=parent)

    def preload_forge_versions(self, parent=None):
        """從 API 取得 Forge 版本並覆蓋寫入 json。"""
        LogUtils.debug("開始載入 Forge 版本...", "LoaderManager")

        # 方法1: 使用新的 Forge API 端點獲取完整版本列表
        LogUtils.debug("嘗試使用 Forge maven metadata API...", "LoaderManager")
        try:
            forge_api_url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
            response = HTTPUtils.get_content(forge_api_url, timeout=15)

            if response and response.status_code == 200:
                LogUtils.debug("成功獲取 Forge XML 數據", "LoaderManager")
                root = etree.fromstring(response.content)
                versions = []

                # 提取所有版本
                for version_elem in root.xpath('//versions/version'):
                    version_text = version_elem.text
                    if version_text and '-' in version_text:
                        versions.append(version_text.strip())

                LogUtils.debug(f"解析出 {len(versions)} 個 Forge 版本", "LoaderManager")

                if len(versions) > 0:
                    # 按 Minecraft 版本分組
                    version_dict = {}
                    for version in versions:
                        if '-' in version:
                            try:
                                parts = version.split('-', 1)
                                if len(parts) == 2:
                                    mc_version = parts[0]
                                    if mc_version not in version_dict:
                                        version_dict[mc_version] = []
                                    version_dict[mc_version].append(version)
                            except Exception:
                                continue

                    # 對每個 MC 版本的 Forge 版本進行排序（最新在前）
                    for mc_version in version_dict:
                        version_dict[mc_version].sort(reverse=True)
                        # 限制每個版本最多10個 Forge 版本，避免數據過多
                        version_dict[mc_version] = version_dict[mc_version][:10]

                    # 寫入快取檔案
                    with open(self.forge_cache_file, "w", encoding="utf-8") as f:
                        json.dump(version_dict, f, ensure_ascii=False, indent=2)
                    return

        except Exception as e:
            LogUtils.debug(f"Maven metadata API 方法失敗: {e}", "LoaderManager")
            UIUtils.show_error(
                "載入 Forge 版本失敗",
                f"無法從 Maven metadata API 獲取 Forge 版本：{e}",
                parent=parent
            )

    def get_compatible_fabric_versions(self, mc_version: str) -> List[LoaderVersion]:
        """
        只從 json 快取檔案取得相容的 Fabric 載入器版本列表。
        Fabric 最早支援 1.14 版本，過濾掉不相容的 MC 版本。
        """
        try:
            # 檢查 MC 版本是否與 Fabric 兼容（1.14+）
            if not self._is_fabric_compatible_version(mc_version):
                return []

            if not os.path.exists(self.fabric_cache_file):
                return []
            with open(self.fabric_cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
            result = []
            # 返回與兼容的MC版本相對應的Fabric加載器版本
            for item in cache:
                if isinstance(item, dict) and "version" in item:
                    ver = item["version"]
                    if ver:
                        result.append(LoaderVersion(version=ver))
            return result
        except Exception:
            return []

    def _is_fabric_compatible_version(self, mc_version: str) -> bool:
        """
        檢查 MC 版本是否與 Fabric 相容。
        Fabric 最早支援 1.14 版本。
        """
        try:
            # 解析 MC 版本以與 1.14 進行比較
            version_parts = self._parse_mc_version(mc_version)
            if not version_parts:
                return False

            major, minor = version_parts[0], version_parts[1] if len(version_parts) > 1 else 0

            # Fabric supports 1.14+
            if major > 1:
                return True
            elif major == 1 and minor >= 14:
                return True
            else:
                return False
        except Exception:
            return False

    def _parse_mc_version(self, version_str: str) -> list:
        """
        解析 MC 版本字串為數字列表，例如 "1.14.4" -> [1, 14, 4]
        """
        try:
            # 提取版本號，處理類似「1.14.4」、「1.14」、「1.20.1」等情況。
            matches = re.findall(r'\d+', version_str)
            return [int(x) for x in matches] if matches else []
        except Exception:
            return []

    def get_compatible_forge_versions(self, mc_version: str) -> List[LoaderVersion]:
        """只從 json 快取檔案取得相容的 Forge 載入器版本列表。"""

        try:
            if not os.path.exists(self.forge_cache_file):
                return []

            with open(self.forge_cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)

            result = []

            # 檢查新格式（完整版本 API）: { "1.21.4": ["1.21.4-54.0.0", "1.21.4-54.0.1", ...] }
            if mc_version in cache and isinstance(cache[mc_version], list):
                for version in cache[mc_version]:
                    # 提取 Forge 版本號（去掉 MC 版本前綴）
                    if "-" in version and version.startswith(mc_version):
                        forge_version = version.split("-", 1)[1]
                        result.append(LoaderVersion(version=forge_version))
                return result

            # 檢查舊格式（promotions API）: "1.21.4-latest": "54.1.5", "1.21.4-recommended": "54.1.0"
            latest_key = f"{mc_version}-latest"
            recommended_key = f"{mc_version}-recommended"

            if latest_key in cache:
                latest_version = cache[latest_key]
                result.append(LoaderVersion(version=latest_version))
                LogUtils.debug(f"找到 latest 版本: {latest_version}", "LoaderManager")

            if recommended_key in cache and cache[recommended_key] != cache.get(latest_key):
                recommended_version = cache[recommended_key]
                result.append(LoaderVersion(version=recommended_version))
                LogUtils.debug(f"找到 recommended 版本: {recommended_version}", "LoaderManager")

            # 檢查其他舊格式以保持相容性: { "mc_version": { "latest": "forge_version" } }
            if not result and mc_version in cache:
                version_info = cache[mc_version]
                LogUtils.debug(f"檢查嵌套格式，version_info 類型: {type(version_info)}", "LoaderManager")
                if isinstance(version_info, dict) and "latest" in version_info:
                    forge_version = version_info["latest"]
                    result.append(LoaderVersion(version=forge_version))
                    LogUtils.debug(f"從嵌套格式找到版本: {forge_version}", "LoaderManager")
                elif isinstance(version_info, str):
                    result.append(LoaderVersion(version=version_info))
                    LogUtils.debug(f"從字串格式找到版本: {version_info}", "LoaderManager")

            return result

        except Exception as e:
            LogUtils.debug(f"獲取 Forge 版本時發生錯誤: {e}", "LoaderManager")
            return []

    # ---------------------- 私有輔助方法 ----------------------
    # === 下載 × 執行安裝器 ===
    def _download_and_run_installer(
        self,
        installer_url: str,
        installer_args: List[str],
        minecraft_version: str,
        loader_version: str,
        download_path: str,
        progress_callback,
        cancel_flag,
        post_msg: str,
        need_vanilla: bool = False,
        parent_window=None
    ) -> Union[bool, str]:
        """
        Fabric 與 Forge 共用：下載安裝器 → （可選）先下載 vanilla → 執行安裝器。
        
            Arg:
                self: LoaderManager 實例。
                installer_url (str): 安裝器的下載 URL。
                installer_args (List[str]): 安裝器的啟動參數。
                minecraft_version (str): Minecraft 版本。
                loader_version (str): 載入器版本。
                download_path (str): 下載路徑。
                progress_callback: 進度回調函數。
                cancel_flag: 取消標誌。
                post_msg (str): 完成後的訊息。
                need_vanilla (bool): 是否需要下載 vanilla 伺服器。

        """
        installer_path = os.path.join(os.path.dirname(download_path), os.path.basename(installer_url))

        # 下載安裝器
        if not self._download_file_with_progress(
            installer_url,
            installer_path,
            progress_callback,
            10,
            30,
            "下載安裝器...",
            cancel_flag,
        ):
            return False

        # 需要 vanilla 伺服器？（Fabric）
        if need_vanilla:
            if not self._download_vanilla_server(
                minecraft_version,
                download_path,
                lambda p, s: progress_callback(30 + p * 0.5, s) if progress_callback else None,
                cancel_flag,
            ):
                return False

        # 執行安裝器
        if progress_callback:
            progress_callback(85, "執行載入器安裝器...")

        cmd = [arg if arg != "{installer}" else installer_path for arg in installer_args]
        result = subprocess.run(
            cmd,
            cwd=os.path.dirname(download_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return self._fail(
                progress_callback,
                f"安裝器執行失敗: {result.stderr}",
                debug=f"[DEBUG] cmd: {' '.join(cmd)}\n{result.stderr}",
            )

        # Forge: 從 run.bat 抽取 java 指令行並完整寫入 start_server.bat
        try:
            base_dir = Path(download_path).parent
            run_bat_path = base_dir / "run.bat"
            run_sh_path = base_dir / "run.sh"
            start_server_path = base_dir / "start_server.bat"
            installer_log_path = base_dir / "installer.log"

            java_line = None

            # 1. 從 run.bat 擷取 java 指令行
            if run_bat_path.exists():
                try:
                    with run_bat_path.open("r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if re.search(r"\bjava\s+@user_jvm_args\\.txt\b", line, re.I):
                                java_line = line.strip()
                                break
                    # 確保加上 nogui
                    if java_line and "nogui" not in java_line.lower():
                        java_line += " nogui"
                except Exception as e:
                    LogUtils.warning(f"無法讀取 run.bat: {e}")

            # 2. 修改 start_server.bat 中以 java 開頭的指令行
            if java_line and start_server_path.exists():
                try:
                    with start_server_path.open("r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()

                    new_lines = []
                    replaced = False
                    for line in lines:
                        if not replaced and re.match(r"^\s*java\b", line, re.I):
                            new_lines.append(java_line + "\n")
                            replaced = True
                        else:
                            new_lines.append(line)

                    with start_server_path.open("w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                except Exception as e:
                    LogUtils.error(f"修改 start_server.bat 失敗: {e}")

            # 3. 清理 run.bat、run.sh、README.txt、installer
            with suppress(FileNotFoundError):
                run_bat_path.unlink()
            with suppress(FileNotFoundError):
                run_sh_path.unlink()
            with suppress(FileNotFoundError):
                (base_dir / "README.txt").unlink()
            with suppress(FileNotFoundError):
                Path(installer_path).unlink()
            with suppress(FileNotFoundError):
                installer_log_path.unlink()

        except Exception:
            LogUtils.debug(f"清理安裝檔失敗: {installer_path}", "LoaderManager")
            UIUtils.show_warning(
                "清理失敗",
                f"安裝完成，但無法清理安裝器檔案：{installer_path}\n可手動刪除。",
                parent=parent_window
            )

        return True

    # === Vanilla ===
    def _download_vanilla_server(
        self,
        minecraft_version: str,
        download_path: str,
        progress_callback,
        cancel_flag,
    ) -> bool:
        """下載 Minecraft Vanilla 伺服器 JAR 檔案。"""
        if progress_callback:
            progress_callback(10, "查詢 Minecraft 版本資訊...")

        server_url = self._get_minecraft_server_url(minecraft_version)
        if not server_url:
            return self._fail(progress_callback, "找不到 Minecraft 版本資訊")

        if progress_callback:
            progress_callback(20, "下載 Minecraft 伺服器...")

        return self._download_file_with_progress(
            server_url,
            download_path,
            progress_callback,
            20,
            100,
            "下載 Minecraft 伺服器...",
            cancel_flag,
        )

    # === 小工具 ===
    def _download_file_with_progress(
        self,
        url: str,
        dest_path: str,
        progress_callback,
        start_percent: int,
        end_percent: int,
        status_text: str,
        cancel_flag: Optional[dict],
    ) -> bool:
        """下載檔案並顯示進度。"""
        try:
            r = HTTPUtils.get_content(url, stream=True, timeout=30)
            if not r:
                return self._fail(progress_callback, "下載失敗：無法獲取檔案")
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 65536
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size):
                    if cancel_flag and cancel_flag.get("cancelled"):
                        return self._fail(progress_callback, "已取消下載")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total and progress_callback:
                            percent = start_percent + (end_percent - start_percent) * (downloaded / total)
                            progress_callback(min(percent, end_percent), status_text)
            if progress_callback:
                progress_callback(end_percent, f"下載完成: {os.path.basename(dest_path)}")
            return True
        except Exception as e:
            return self._fail(
                progress_callback,
                f"下載失敗: {e}",
                debug=f"[DEBUG] download error {url} -> {dest_path}: {e}",
            )

    def _get_minecraft_server_url(self, mc_version: str) -> Optional[str]:
        """根據 Minecraft 版本獲取伺服器 JAR 下載 URL。"""
        try:
            manifest = HTTPUtils.get_json("https://launchermeta.mojang.com/mc/game/version_manifest.json", timeout=10)
            if not manifest:
                return None
            ver_url = next(v["url"] for v in manifest["versions"] if v["id"] == mc_version)
            ver_data = HTTPUtils.get_json(ver_url, timeout=10)
            if not ver_data:
                return None
            return ver_data["downloads"]["server"]["url"]
        except Exception:
            return None

    def _standardize_loader_type(self, lt: str, loader_version: str) -> str:
        """標準化載入器類型：將輸入轉為小寫並進行基本推斷。"""
        lt_low = lt.lower()
        if lt_low != "unknown":
            return lt_low
        # fallback 推斷
        if loader_version.replace(".", "").isdigit():
            return "forge"
        if "fabric" in loader_version.lower():
            return "fabric"
        return "vanilla"

    def _fail(self, progress_callback, user_msg: str, debug: str = "") -> bool:
        """通用失敗處理：顯示錯誤訊息並回傳 False。"""
        if debug:
            print(debug)
        if progress_callback:
            progress_callback(100, user_msg)
        return False
