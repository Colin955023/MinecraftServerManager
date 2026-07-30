"""
建立伺服器服務模組
負責表單參數驗證、伺服器設定建構與背景下載流程之協調。
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import ServerConfig
from ..utils import MemoryUtils, get_logger

logger = get_logger().bind(component="CreateServerService")


@dataclass
class ValidationResult:
    """驗證結果"""

    is_valid: bool
    errors: list[str]
    memory_warning: str | None = None
    memory_color: str | None = None


@dataclass
class ServerConfigInputs:
    """建立伺服器表單輸入"""

    server_name: str
    mc_version: str
    loader_type: str
    loader_version: str
    min_memory: str
    max_memory: str
    system_memory: int
    servers_root: str


class CreateServerService:
    """建立伺服器服務類別。"""

    @staticmethod
    def compose_server_name(loader_type: str, mc_version: str, suffix: str = "") -> str:
        """
        依載入器類型與版本組合標準伺服器名稱。

        Args:
            loader_type (str): 載入器類型，例如 "Fabric"、"Forge"、"Quilt" 或 "NeoForge"
            mc_version (str): Minecraft 版本
            suffix (str): 自訂尾字

        Returns:
            str: 組合後的伺服器名稱
        """
        base_name = f"{mc_version}{suffix}"
        if loader_type in ("Fabric", "Forge", "Quilt", "NeoForge"):
            return f"{loader_type} {base_name}"
        return base_name

    @staticmethod
    def extract_server_name_suffix(name: str, version_candidates: tuple[str, ...]) -> str | None:
        """
        解析「[載入器前綴] + 版本 + 自訂尾字」中的尾字。

        Args:
            name (str): 伺服器名稱
            version_candidates (tuple[str, ...]): 可能的版本字串列表

        Returns:
            str | None: 解析出的尾字，若無法解析則返回 None
        """
        normalized = name.strip()
        if not normalized:
            return None
        for prefix in ("Fabric ", "Forge ", "Quilt ", "NeoForge "):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        for version in version_candidates:
            if version and normalized.startswith(version):
                return normalized[len(version) :]
        return None

    @staticmethod
    def validate_download_parameters(loader_type: str, config: ServerConfig) -> bool:
        """
        驗證下載參數合法性。

        Args:
            loader_type (str): 載入器類型
            config (ServerConfig): 伺服器設定

        Returns:
            bool: 參數是否合法
        """
        if not loader_type or loader_type == "unknown":
            return False
        if not config.minecraft_version or config.minecraft_version == "unknown":
            return False
        requires_loader_version = loader_type in ["forge", "fabric", "quilt", "neoforge"]
        return not (requires_loader_version and (not config.loader_version or config.loader_version == "unknown"))

    @staticmethod
    def validate_server_config_inputs(inputs: ServerConfigInputs) -> ValidationResult:
        """
        驗證伺服器設定輸入。

        Args:
            inputs (ServerConfigInputs): 伺服器設定輸入

        Returns:
            ValidationResult: 驗證結果
        """
        errors = []
        if not inputs.server_name:
            errors.append("伺服器名稱不可為空")
        if not inputs.mc_version or inputs.mc_version in ["載入中...", "無可用版本", "載入失敗"]:
            errors.append("請選擇有效的 Minecraft 版本")
        if inputs.loader_type != "Vanilla" and (
            not inputs.loader_version or inputs.loader_version in ["無", "載入中...", "無可用版本", "載入失敗"]
        ):
            errors.append("請選擇有效的載入器版本")

        if not inputs.max_memory:
            errors.append("最大記憶體為必填")

        min_mem = 0
        max_mem = 0
        try:
            min_mem = int(inputs.min_memory) if inputs.min_memory else 0
            max_mem = int(inputs.max_memory) if inputs.max_memory else 0
            if min_mem > max_mem and min_mem > 0:
                errors.append("最小記憶體不可大於最大記憶體")
        except ValueError:
            errors.append("記憶體設定必須為有效整數")
            min_mem = -1

        memory_warning = None
        memory_color = None
        if min_mem != -1 and max_mem > 0:
            mem_result = MemoryUtils.check_memory_limits(min_mem, max_mem, inputs.system_memory)
            if mem_result.color in ("error", "warning"):
                memory_warning = mem_result.warning_text
                memory_color = mem_result.color

        return ValidationResult(
            is_valid=len(errors) == 0, errors=errors, memory_warning=memory_warning, memory_color=memory_color
        )

    @staticmethod
    def build_server_config(inputs: ServerConfigInputs) -> ServerConfig:
        """
        根據表單輸入建立伺服器設定。

        Args:
            inputs (ServerConfigInputs): 伺服器設定輸入

        Returns:
            ServerConfig: 建立的伺服器設定
        """
        min_mem = int(inputs.min_memory) if inputs.min_memory else None
        max_mem = int(inputs.max_memory)
        return ServerConfig(
            name=inputs.server_name,
            minecraft_version=inputs.mc_version,
            loader_type=inputs.loader_type,
            loader_version=inputs.loader_version if inputs.loader_type != "Vanilla" else "",
            memory_max_mb=max_mem,
            memory_min_mb=min_mem,
            path=str(Path(inputs.servers_root) / inputs.server_name),
        )

    @staticmethod
    def execute_server_creation(
        config: ServerConfig,
        server_crud: Any,
        loader_manager: Any,
        progress_callback: Callable[[int, str], bool],
        cancel_token: Any,
        user_java_path: str | None = None,
        ask_proceed_callback: Callable[[str, str], bool] | None = None,
    ) -> None:
        """
        執行伺服器建立的流程。
        這包含建立資料夾、下載核心等。

        Args:
            config (ServerConfig): 伺服器設定
            server_crud (Any): 伺服器 CRUD 服務
            loader_manager (Any): 載入器管理器
            progress_callback (Callable[[int, str], bool]): 進度回呼函式
            cancel_token (Any): 取消令牌
            user_java_path (str | None): 使用者指定的 Java 路徑
            ask_proceed_callback (Callable[[str, str], bool] | None): 詢問使用者是否繼續的回呼函式
        """
        if progress_callback(5, "建立伺服器目錄結構...") is False:
            return

        create_result = server_crud.create_server_result(config)
        if create_result.failed:
            raise Exception(create_result.message or "建立伺服器基礎結構失敗")

        if not config.loader_type or config.loader_type == "unknown":
            raise Exception(f"偵測失敗：loader_type 無法判斷，config={config}")
        if not config.minecraft_version or config.minecraft_version == "unknown":
            raise Exception(f"偵測失敗：minecraft_version 無法判斷，config={config}")
        if config.loader_type.lower() in ["forge", "fabric", "quilt", "neoforge"] and (
            not config.loader_version or config.loader_version == "unknown"
        ):
            raise Exception(f"偵測失敗：loader_version 無法判斷，config={config}")

        server_path = Path(config.path)
        if progress_callback(15, "下載伺服器核心檔案...") is False:
            return

        loader_type = config.loader_type.lower()
        download_path = str(server_path / "server.jar")

        installer_url = loader_manager.get_installer_download_url(
            loader_type,
            config.minecraft_version,
            config.loader_version,
        )
        if installer_url:
            checksum = loader_manager._fetch_secure_checksum(installer_url)
            if checksum is None and ask_proceed_callback:
                proceed = ask_proceed_callback(
                    "缺少驗證資訊",
                    f"{config.loader_type} 安裝器目前找不到 SHA-256 / SHA-512 驗證資訊。\n仍要繼續建立伺服器嗎？",
                )
                if not proceed:
                    return

        with contextlib.suppress(Exception):
            server_path.mkdir(parents=True, exist_ok=True)
        time.sleep(0.3)

        if not CreateServerService.validate_download_parameters(loader_type, config):
            raise Exception(
                f"下載流程參數異常: loader_type={loader_type} mc={config.minecraft_version} loader_ver={config.loader_version}"
            )

        ok = loader_manager.download_server_jar_with_progress(
            loader_type,
            config.minecraft_version,
            config.loader_version,
            download_path,
            progress_callback,
            cancel_token,
            user_java_path,
        )
        if not ok:
            log_details = [
                f"loader_type: {loader_type}",
                f"minecraft_version: {config.minecraft_version}",
                f"loader_version: {config.loader_version}",
                f"download_path: {download_path}",
                f"user_java_path: {user_java_path or '未設定'}",
            ]
            try:
                possible_logs = [server_path / "installer.log"]
                for log_path in possible_logs:
                    if log_path.exists():
                        log_details.append(
                            f"\n--- {log_path.name} ---\n"
                            + log_path.read_text(encoding="utf-8", errors="ignore")[-2048:]
                        )
            except Exception as e:
                log_details.append(f"[installer.log 讀取失敗: {e}]")
            msg = "伺服器下載失敗，參數如下：\n" + "\n".join(log_details)
            raise Exception(msg)

        server_crud.create_launch_script(config)
        progress_callback(100, "伺服器建立完成！")
