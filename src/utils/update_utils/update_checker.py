"""應用程式更新檢查器模組
提供 GitHub Release 版本檢查與自動下載安裝功能
"""

import html as _html
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
import markdown as _markdown
from packaging.version import Version
from ...ui import TaskUtils
from .. import HTTPUtils
from .. import PathUtils
from .. import RuntimePaths
from .. import SubprocessUtils
from .. import UIUtils
from .update_parsing import UpdateParsing
from .. import get_logger

logger = get_logger().bind(component="UpdateChecker")


class UpdateChecker:
    """集中處理 GitHub Releases 更新檢查與安裝流程。"""

    @staticmethod
    def _parse_version(version_str: str | None) -> Version | None:
        """解析版本字串為 PEP 440 Version 物件。"""
        return UpdateParsing.parse_version(version_str)

    @staticmethod
    def _get_latest_release(owner: str, repo: str, include_prerelease: bool = False) -> dict | None:
        return UpdateParsing.get_latest_release(owner, repo, include_prerelease=include_prerelease)

    @staticmethod
    def _is_development_environment() -> bool:
        """僅在開發環境允許偵測 prerelease。"""
        return not RuntimePaths.is_packaged()

    @staticmethod
    def _choose_installer_asset(release: dict) -> dict:
        return UpdateParsing.choose_installer_asset(release)

    @staticmethod
    def _select_update_asset(release: dict, portable_mode: bool) -> tuple[dict, str]:
        return UpdateParsing.select_update_asset(release, portable_mode)

    @staticmethod
    def _escape_powershell_single_quoted_literal(value: str) -> str:
        """
        回傳可安全嵌入 PowerShell 單引號字串的文字。

        Args:
            value: 任意字串。

        Returns:
            已轉義的字串，適合放在 PowerShell 單引號字串中。
        """
        return "'" + value.replace("'", "''") + "'"

    @staticmethod
    def _build_portable_update_script(
        source_dir: Path,
        destination_dir: Path,
        backup_dir: Path,
        cleanup_dir: Path,
        executable_name: str = "MinecraftServerManager.exe",
    ) -> str:
        """產生 portable 更新流程使用的 PowerShell 腳本。

        Args:
            source_dir: 更新檔解壓來源目錄。
            destination_dir: 最終安裝目錄。
            backup_dir: 原始安裝備份目錄。
            cleanup_dir: 解壓暫存目錄。
            executable_name: 啟動用可執行檔名稱。

        Returns:
            可直接寫入 `.ps1` 檔案的腳本文字。
        """
        source_literal = UpdateChecker._escape_powershell_single_quoted_literal(str(source_dir))
        destination_literal = UpdateChecker._escape_powershell_single_quoted_literal(str(destination_dir))
        backup_literal = UpdateChecker._escape_powershell_single_quoted_literal(str(backup_dir))
        cleanup_literal = UpdateChecker._escape_powershell_single_quoted_literal(str(cleanup_dir))
        exe_literal = UpdateChecker._escape_powershell_single_quoted_literal(executable_name)
        lines = [
            "$ErrorActionPreference = 'Stop'",
            f"$sourceDir = {source_literal}",
            f"$destinationDir = {destination_literal}",
            f"$backupDir = {backup_literal}",
            f"$cleanupDir = {cleanup_literal}",
            f"$executableName = {exe_literal}",
            "for ($count = 0; $count -lt 20; $count++) {",
            "    $process = Get-Process -Name 'MinecraftServerManager' -ErrorAction SilentlyContinue",
            "    if (-not $process) {",
            "        break",
            "    }",
            "    Start-Sleep -Seconds 1",
            "}",
            "Start-Sleep -Seconds 3",
            "if (Test-Path -LiteralPath $destinationDir) {",
            "    Get-ChildItem -LiteralPath $destinationDir -Force | ForEach-Object {",
            "        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue",
            "    }",
            "}",
            "if (Test-Path -LiteralPath $sourceDir) {",
            "    Get-ChildItem -LiteralPath $sourceDir -Force | ForEach-Object {",
            "        Copy-Item -LiteralPath $_.FullName -Destination $destinationDir -Recurse -Force",
            "    }",
            "}",
            "$configSource = Join-Path $backupDir '.config'",
            "if (Test-Path -LiteralPath $configSource) {",
            "    $configDestination = Join-Path $destinationDir '.config'",
            "    New-Item -ItemType Directory -Force -Path $configDestination | Out-Null",
            "    Get-ChildItem -LiteralPath $configSource -Force | ForEach-Object {",
            "        Copy-Item -LiteralPath $_.FullName -Destination $configDestination -Recurse -Force",
            "    }",
            "}",
            "$logSource = Join-Path $backupDir '.log'",
            "if (Test-Path -LiteralPath $logSource) {",
            "    $logDestination = Join-Path $destinationDir '.log'",
            "    New-Item -ItemType Directory -Force -Path $logDestination | Out-Null",
            "    Get-ChildItem -LiteralPath $logSource -Force | ForEach-Object {",
            "        Copy-Item -LiteralPath $_.FullName -Destination $logDestination -Recurse -Force",
            "    }",
            "}",
            "$portableMarker = Join-Path $destinationDir '.portable'",
            "if (-not (Test-Path -LiteralPath $portableMarker)) {",
            "    New-Item -ItemType File -Force -Path $portableMarker | Out-Null",
            "}",
            "try {",
            "    $portableFile = Get-Item -LiteralPath $portableMarker -ErrorAction Stop",
            "    $portableFile.Attributes = $portableFile.Attributes -bor [System.IO.FileAttributes]::Hidden",
            "} catch {",
            '    Write-Verbose "無法隱藏 .portable 標記：$($_.Exception.Message)"',
            "}",
            "Start-Sleep -Seconds 2",
            "Start-Process -FilePath (Join-Path $destinationDir $executableName) -WorkingDirectory $destinationDir",
            "Remove-Item -LiteralPath $cleanupDir -Recurse -Force -ErrorAction SilentlyContinue",
            "Start-Sleep -Seconds 5",
            "Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue",
            "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue",
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _launch_installer(installer_path: Path, parent=None) -> None:
        """啟動安裝程式

        Args:
            installer_path: 安裝程式檔案路徑
            parent: 父視窗物件，用於在主執行緒顯示 UI 對話框
        """
        try:
            try:
                temp_dir = Path(tempfile.gettempdir()).resolve(strict=True)
                resolved_path = installer_path.resolve(strict=True)
            except FileNotFoundError as e:
                logger.error(f"安裝程式路徑解析失敗：{installer_path}，錯誤：{e}")
                return
            except Exception as e:
                logger.error(f"解析安裝程式路徑時發生未預期錯誤：{installer_path}，錯誤：{e}")
                return
            if not PathUtils.is_path_within(temp_dir, resolved_path, strict=True):
                logger.error(f"安裝程式路徑不在允許的暫存目錄中：{resolved_path}")
                return
            if resolved_path.is_file():
                confirm = TaskUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.ask_yes_no_cancel(
                        "執行安裝程式",
                        f"即將執行安裝程式：\n{resolved_path}\n\n是否確定要執行？",
                        parent=parent,
                        show_cancel=False,
                        topmost=True,
                    ),
                )
                if not confirm:
                    logger.info(f"使用者取消執行安裝程式：{resolved_path}")
                    return
                process = SubprocessUtils.popen_detached([str(resolved_path)])
                time.sleep(0.5)
                returncode = process.poll()
                if returncode is not None:
                    if returncode != 0:
                        logger.error(f"安裝程式啟動失敗，退出碼：{returncode}")
                        return
                    logger.debug(f"安裝程式進程已退出（可能啟動了子進程），退出碼：{returncode}")
                logger.info(f"已啟動安裝程式（PID: {process.pid}）: {resolved_path}")
            else:
                logger.error(f"安裝程式不存在或不是檔案：{resolved_path}")
        except Exception as e:
            logger.exception(f"安裝程式啟動失敗: {e}")

    @staticmethod
    def _graceful_exit(parent, delay_ms: int = 100) -> None:
        """優雅地關閉應用程式

        Args:
            parent: 父視窗物件
            delay_ms: 延遲關閉的毫秒數
        """
        try:
            if parent is not None and hasattr(parent, "after") and hasattr(parent, "winfo_exists"):

                def _close():
                    try:
                        if parent.winfo_exists():
                            parent.quit()
                            parent.destroy()
                    except Exception as e:
                        logger.exception(f"關閉視窗失敗: {e}")
                    finally:
                        sys.exit(0)

                UIUtils.schedule_debounce(
                    parent, "_update_graceful_exit_job", max(0, int(delay_ms)), _close, owner=parent
                )
                return
        except Exception as e:
            logger.debug(f"安排視窗關閉時發生錯誤: {e}")
        sys.exit(0)

    @staticmethod
    def _clean_release_notes(body: str) -> str:
        """
        清理並篩選釋出說明，過濾開發者資訊與過長內容
        僅保留: 新增功能、修改、刪除、優化等使用者相關資訊
        濾除: 開發者資訊 (contributors, full changelog 連結, PR 作者資訊)
        """
        if not body:
            return "(無釋出說明)"
        lines = body.splitlines()
        kept_lines = []
        ignoring = False
        for line in lines:
            l_strip = line.strip()
            l_lower = l_strip.lower()
            if "new contributors" in l_lower or "full changelog" in l_lower:
                ignoring = True
                if "full changelog" in l_lower:
                    break
                continue
            if ignoring:
                if l_strip.startswith("#"):
                    ignoring = False
                else:
                    continue
            clean_line = re.sub("\\s+by\\s+@[\\w\\-]+", "", line)
            clean_line = re.sub("\\s+in\\s+https://\\S+", "", clean_line)
            if not clean_line.strip():
                continue
            kept_lines.append(clean_line)
        text = "\n".join(kept_lines)
        try:
            html = _markdown.markdown(text)
            text_only = re.sub("<[^<]+?>", "", html)
            decoded = _html.unescape(text_only)
        except Exception:
            decoded = text
        final_lines = [x for x in decoded.splitlines() if x.strip()]
        if len(final_lines) > 15:
            final_lines = final_lines[:15]
            final_lines.append("... (完整內容請查看發行頁面)")
        return "\n".join(final_lines)

    @staticmethod
    def check_and_prompt_update(
        current_version: str, owner: str, repo: str, show_up_to_date_message: bool = True, parent=None
    ) -> None:
        """檢查最新版本並在需要時提示使用者進行更新。

        Args:
            current_version: 目前版本字串。
            owner: GitHub repository owner。
            repo: GitHub repository 名稱。
            show_up_to_date_message: 是否在已是最新版本時顯示提示。
            parent: 父視窗物件。
        """

        def _work() -> None:
            temp_files_to_cleanup: list[Path] = []

            def _cleanup_temp_files(temp_files: list[Path]) -> None:
                """清理所有下載的暫存檔案"""
                for temp_path in temp_files:
                    try:
                        if temp_path.exists():
                            if temp_path.is_file():
                                temp_path.unlink(missing_ok=True)
                                logger.debug(f"已刪除暫存檔案: {temp_path}")
                            elif temp_path.is_dir():
                                shutil.rmtree(temp_path, ignore_errors=True)
                                logger.debug(f"已刪除暫存目錄: {temp_path}")
                    except Exception as e:
                        logger.debug(f"清理暫存檔案時發生錯誤 {temp_path}: {e}")

            def _handle_checksum_mismatch(asset_name: str) -> None:
                """統一處理下載檔案 SHA256 驗證失敗。"""
                logger.error(f"[驗證失敗] SHA256 不符合！檔案: {asset_name}")
                TaskUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.show_error(
                        "SHA256 驗證失敗",
                        "下載的檔案 SHA256 驗證失敗！\n\n可能原因：\n• 下載過程中檔案損壞\n• 檔案被惡意篡改\n• 網路傳輸錯誤\n\n為了您的安全：\n- 已立即刪除下載的檔案\n- 更新已取消\n\n請稍後重試，或手動從 GitHub 下載。",
                        parent=parent,
                        topmost=True,
                    ),
                )
                _cleanup_temp_files(temp_files_to_cleanup)

            try:
                logger.info(f"開始檢查更新... (目前版本: {current_version})")
                include_prerelease = UpdateChecker._is_development_environment()
                latest = UpdateChecker._get_latest_release(owner, repo, include_prerelease=include_prerelease)
                if not latest:
                    logger.info("無法從 GitHub 取得最新版本資訊")
                    if show_up_to_date_message:
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_info(
                                "檢查更新",
                                "無法取得最新版本資訊，或沒有可用的正式發布版本。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                    return
                latest_tag = latest.get("tag_name") or ""
                latest_ver = UpdateChecker._parse_version(latest_tag)
                current_ver = UpdateChecker._parse_version(current_version)
                if not latest_ver or not current_ver:
                    logger.warning("無法解析版本號，跳過更新檢查")
                    return
                logger.info(f"版本檢查: 目前版本={current_ver}, 最新版本={latest_ver} ({latest_tag})")
                if latest_ver <= current_ver:
                    logger.info("目前已是最新版本")
                    if show_up_to_date_message:
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_info(
                                "檢查更新",
                                f"目前版本 {current_version} 已是最新版本，無須更新。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                    return
                name = latest.get("name") or latest_tag
                logger.info(f"發現新版本: {name}")
                body = latest.get("body") or "(無釋出說明)"
                rendered = UpdateChecker._clean_release_notes(body)
                html_url = latest.get("html_url")
                msg = f"發現新版本：{name}\n目前版本：{current_version}\n\n釋出說明：\n{rendered}\n\n是否下載並安裝？"
                result = TaskUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.ask_yes_no_cancel("更新可用", msg, parent=parent, show_cancel=False, topmost=True),
                )
                if not result:
                    return
                logger.info("使用者確認更新，準備下載...")
                portable_mode = RuntimePaths.is_portable_mode()
                asset, asset_mode = UpdateChecker._select_update_asset(latest, portable_mode)
                if asset_mode == "installer_fallback":
                    logger.info("可攜式更新資源不存在，回退使用 installer 資源")
                if not asset:
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "無安裝檔",
                            "找不到可用的安裝檔（.exe 或 portable.zip）。將開啟發行頁面，請手動下載。",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    if html_url:
                        UIUtils.open_external(html_url)
                    return
                download_url = asset.get("browser_download_url")
                if not download_url:
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_error(
                            "無下載連結",
                            "選取的安裝檔缺少下載連結。將開啟發行頁面，請手動下載最新版本。",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    if html_url:
                        UIUtils.open_external(html_url)
                    return

                def _parse_asset_digest(asset_dict: dict) -> tuple[str, str] | None:
                    return UpdateParsing.parse_asset_digest(asset_dict)

                def _fetch_checksum_for_asset(release: dict) -> tuple[str, str] | None:
                    """
                    只從 GitHub release asset digest 取得 checksum。

                    若 asset 未提供 digest，直接回傳 None。
                    """
                    try:
                        asset_obj = release.get("_selected_asset") or {}
                        if asset_obj:
                            digest = _parse_asset_digest(asset_obj)
                            if digest:
                                logger.info(
                                    f"[SHA256 查詢成功] 已從 GitHub asset digest 取得 checksum（{digest[0]}），無需額外下載"
                                )
                                return digest
                        logger.warning("[SHA256 查詢失敗] GitHub asset digest 不存在或無法解析，已拒絕使用未驗證檔案")
                        return None
                    except Exception as e:
                        logger.exception(f"[SHA256 查詢錯誤] 在查詢過程中發生未預期的錯誤: {e}")
                    return None

                def _verify_file_checksum(path: Path, algorithm: str, hex_checksum: str) -> bool:
                    checksum = PathUtils.calculate_checksum(path, algorithm)
                    return checksum == hex_checksum.lower() if checksum else False

                if asset_mode == "portable" and download_url and str(download_url).lower().endswith(".zip"):
                    if not TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.ask_yes_no_cancel(
                            "可攜式更新可用",
                            f"發現可攜式更新：{name}\n是否下載並套用？\n（會備份整個應用程式與 .config/.log，確保可恢復）",
                            parent=parent,
                            show_cancel=False,
                            topmost=True,
                        ),
                    ):
                        return
                    logger.info("使用者確認更新，開始更新流程")
                    close_delay_seconds = 3
                    logger.info("[安全檢查] 正在線上查詢更新檔的 SHA256 驗證資訊...")
                    try:
                        latest["_selected_asset"] = asset
                        chk = _fetch_checksum_for_asset(latest)
                        if not chk:
                            logger.error("[安全檢查失敗] 未找到 SHA256，拒絕下載未經驗證的檔案")
                            TaskUtils.call_on_ui(
                                parent,
                                lambda: UIUtils.show_error(
                                    "缺少 SHA256 驗證資訊",
                                    "無法從 GitHub Release 中取得此更新檔的 SHA256 驗證資訊。\n\n為了您的系統安全：\n- 將不會下載任何檔案\n- 更新已取消\n\n建議聯絡開發者確認 Release 是否包含 SHA256 資訊。",
                                    parent=parent,
                                    topmost=True,
                                ),
                            )
                            _cleanup_temp_files(temp_files_to_cleanup)
                            return
                        alg, expected_checksum = chk
                        logger.info(f"[安全檢查通過] 已取得 SHA256 驗證資訊 ({alg}: {expected_checksum[:16]}...)")
                        logger.info("[開始下載] 確認有 SHA256 可驗證，現在開始安全下載主檔案")
                    except Exception:
                        logger.exception("[安全檢查錯誤] 在查詢 SHA256 時發生錯誤，為避免風險將中止更新")
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "安全驗證錯誤",
                                "在線上查詢 SHA256 驗證資訊時發生錯誤。\n\n為了您的系統安全：\n- 將不會下載任何檔案\n- 更新已取消",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    logger.info("[下載階段] 開始下載可攜式更新檔...")
                    with tempfile.NamedTemporaryFile(delete=False, prefix="msm_portable_", suffix=".zip") as tmpf:
                        tmp_zip_path = tmpf.name
                    temp_files_to_cleanup.append(Path(tmp_zip_path))
                    if not HTTPUtils.download_file(download_url, tmp_zip_path):
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error("下載失敗", "無法下載可攜式更新。", parent=parent, topmost=True),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    logger.info("[驗證階段] 正在計算並驗證下載檔案的 SHA256...")
                    logger.info(f"[驗證階段] 預期 SHA256: {expected_checksum}")
                    ok = _verify_file_checksum(Path(tmp_zip_path), alg, expected_checksum)
                    if not ok:
                        _handle_checksum_mismatch(asset.get("name") or "unknown")
                        return
                    logger.info(f"[驗證通過] SHA256 驗證成功：{asset.get('name')}")
                    extracted_dir = Path(tempfile.mkdtemp(prefix="msm_portable_extracted_"))
                    temp_files_to_cleanup.append(extracted_dir)
                    try:
                        PathUtils.safe_extract_zip(Path(tmp_zip_path), extracted_dir)
                    except Exception as e:
                        logger.exception(f"解壓更新檔失敗: {e}")
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "解壓失敗", "無法解壓下載的更新檔。", parent=parent, topmost=True
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    base = RuntimePaths.get_portable_base_dir()
                    cfg = base / ".config"
                    lg = base / ".log"
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "更新中", "正在應用更新，程式將在 3 秒後關閉...", parent=parent, topmost=True
                        ),
                    )
                    logger.info("通知使用者程式將關閉進行更新")
                    backup_root = Path(tempfile.mkdtemp(prefix="msm_portable_backup_"))
                    logger.info(f"開始備份原始目錄與配置: {backup_root}")
                    try:
                        backup_dir = backup_root / "original"
                        PathUtils.copy_dir(base, backup_dir, ignore_patterns=[".config", ".log", ".portable"])
                        if cfg.exists():
                            PathUtils.copy_dir(cfg, backup_root / ".config")
                            logger.info("已備份 .config")
                        if lg.exists():
                            PathUtils.copy_dir(lg, backup_root / ".log")
                            logger.info("已備份 .log")
                    except Exception as e:
                        error_msg = str(e)
                        logger.exception(f"備份失敗: {error_msg}")
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "備份失敗",
                                f"無法備份現有配置，停止更新以確保安全。\n{error_msg}",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        return
                    try:
                        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
                        extracted_dir_resolved = extracted_dir.resolve(strict=True)
                        backup_root_resolved = backup_root.resolve(strict=True)
                        base.resolve(strict=True)
                        if not PathUtils.is_path_within(temp_root, extracted_dir_resolved, strict=True):
                            logger.error(f"解壓目錄不在暫存目錄中，已取消更新：{extracted_dir_resolved}")
                            TaskUtils.call_on_ui(
                                parent,
                                lambda: UIUtils.show_error(
                                    "安全錯誤",
                                    "偵測到異常的解壓路徑，已取消更新以確保安全。",
                                    parent=parent,
                                    topmost=True,
                                ),
                            )
                            _cleanup_temp_files(temp_files_to_cleanup)
                            return
                        if not PathUtils.is_path_within(temp_root, backup_root_resolved, strict=True):
                            logger.error(f"備份目錄不在暫存目錄中，已取消更新：{backup_root_resolved}")
                            TaskUtils.call_on_ui(
                                parent,
                                lambda: UIUtils.show_error(
                                    "安全錯誤",
                                    "偵測到異常的備份路徑，已取消更新以確保安全。",
                                    parent=parent,
                                    topmost=True,
                                ),
                            )
                            _cleanup_temp_files(temp_files_to_cleanup)
                            return
                    except Exception as e:
                        logger.exception(f"驗證路徑時發生錯誤: {e}")
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "錯誤", "路徑驗證失敗，已取消更新。", parent=parent, topmost=True
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    source_dir = Path(extracted_dir).expanduser()
                    cleanup_dir = Path(extracted_dir).expanduser()
                    destination_dir = Path(base).expanduser()
                    backup_dir = Path(backup_root).expanduser()
                    extracted_items = list(extracted_dir.iterdir())
                    if (
                        len(extracted_items) == 1
                        and extracted_items[0].is_dir()
                        and (extracted_items[0].name == "MinecraftServerManager")
                    ):
                        source_dir = Path(extracted_items[0]).expanduser()
                        logger.info(f"檢測到嵌套資料夾，調整源路徑為: {source_dir}")
                    script = UpdateChecker._build_portable_update_script(
                        source_dir=source_dir,
                        destination_dir=destination_dir,
                        backup_dir=backup_dir,
                        cleanup_dir=cleanup_dir,
                    )
                    apply_script = temp_root / "apply_update.ps1"
                    try:
                        apply_script.write_text(script, encoding="utf-8")
                    except Exception:
                        logger.exception("寫入 PowerShell 更新腳本失敗")
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error("錯誤", "無法建立套用更新的腳本。", parent=parent, topmost=True),
                        )
                        return
                    try:
                        apply_script_resolved = apply_script.resolve(strict=True)
                        if not PathUtils.is_path_within(temp_root, apply_script_resolved, strict=True):
                            logger.error(
                                "套用更新腳本的路徑不在暫存目錄中，已拒絕執行。",
                                apply_script=str(apply_script_resolved),
                                temp_root=str(temp_root),
                            )
                            TaskUtils.call_on_ui(
                                parent,
                                lambda: UIUtils.show_error(
                                    "錯誤",
                                    "偵測到異常的更新腳本路徑，已取消自動更新以確保安全。",
                                    parent=parent,
                                    topmost=True,
                                ),
                            )
                            return
                        powershell_executable = (
                            PathUtils.find_executable("pwsh") or PathUtils.find_executable("powershell") or "powershell"
                        )
                        SubprocessUtils.popen_detached(
                            [
                                str(powershell_executable),
                                "-NoLogo",
                                "-NoProfile",
                                "-NonInteractive",
                                "-ExecutionPolicy",
                                "Bypass",
                                "-File",
                                str(apply_script_resolved),
                            ],
                            cwd=str(apply_script_resolved.parents[0]),
                        )
                    except Exception:
                        logger.exception("啟動套用更新腳本失敗")
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    logger.info("更新腳本已啟動，準備關閉程式以進行更新")
                    if extracted_dir in temp_files_to_cleanup:
                        temp_files_to_cleanup.remove(extracted_dir)
                    _cleanup_temp_files(temp_files_to_cleanup)
                    time.sleep(close_delay_seconds)
                    UpdateChecker._graceful_exit(parent)
                    return
                logger.info("[安全檢查] 正在線上查詢安裝程式的 SHA256 驗證資訊...")
                try:
                    latest["_selected_asset"] = asset
                    chk = _fetch_checksum_for_asset(latest)
                    if not chk:
                        logger.error("[安全檢查失敗] 未找到 SHA256，拒絕下載未經驗證的檔案")
                        TaskUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "缺少 SHA256 驗證資訊",
                                "無法從 GitHub Release 中取得此安裝程式的 SHA256 驗證資訊。\n\n為了您的系統安全：\n- 將不會下載任何檔案\n- 更新已取消\n\n建議聯絡開發者確認 Release 是否包含 SHA256 資訊。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    alg, expected_checksum = chk
                    logger.info(f"[安全檢查通過] 已取得 SHA256 驗證資訊 ({alg}: {expected_checksum[:16]}...)")
                    logger.info("[開始下載] 確認有 SHA256 可驗證，現在開始安全下載安裝程式")
                except Exception:
                    logger.exception("[安全檢查錯誤] 在查詢 SHA256 時發生錯誤，為避免風險將中止更新")
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_error(
                            "安全驗證錯誤",
                            "在線上查詢 SHA256 驗證資訊時發生錯誤。\n\n為了您的系統安全：\n- 將不會下載任何檔案\n- 更新已取消",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    _cleanup_temp_files(temp_files_to_cleanup)
                    return
                logger.info("[下載階段] 開始下載安裝程式...")
                with tempfile.NamedTemporaryFile(delete=False, prefix="msm_update_", suffix=".exe") as tmp:
                    temp_path = tmp.name
                dest = Path(temp_path)
                temp_files_to_cleanup.append(dest)
                if HTTPUtils.download_file(download_url, str(dest)):
                    logger.info("[驗證階段] 正在計算並驗證下載檔案的 SHA256...")
                    logger.info(f"[驗證階段] 預期 SHA256: {expected_checksum}")
                    ok = _verify_file_checksum(dest, alg, expected_checksum)
                    if not ok:
                        _handle_checksum_mismatch(asset.get("name") or "unknown")
                        return
                    logger.info(f"[驗證通過] SHA256 驗證成功：{asset.get('name')}")
                    UpdateChecker._launch_installer(dest, parent=parent)
                    logger.info("安裝程式已啟動（獨立進程）")
                    if dest in temp_files_to_cleanup:
                        temp_files_to_cleanup.remove(dest)
                    _cleanup_temp_files(temp_files_to_cleanup)
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "更新準備就緒",
                            "安裝程式已啟動。\n\n程式將在關閉此訊息後結束。\n請依安裝程式指示完成更新。",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    time.sleep(2)
                    logger.info("準備關閉當前程式以完成更新")
                    UpdateChecker._graceful_exit(parent)
                else:
                    TaskUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_error(
                            "下載失敗", "無法下載安裝檔，請稍後再試。", parent=parent, topmost=True
                        ),
                    )
                    _cleanup_temp_files(temp_files_to_cleanup)
            except Exception as e:
                logger.exception(f"更新檢查失敗: {e}")
                error_msg = str(e)
                TaskUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.show_error(
                        "更新檢查失敗", f"無法完成更新檢查或下載：{error_msg}", parent=parent, topmost=True
                    ),
                )
                _cleanup_temp_files(temp_files_to_cleanup)

        TaskUtils.run_async(_work)
