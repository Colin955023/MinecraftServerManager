"""應用程式更新檢查器模組
提供 GitHub Release 版本檢查與自動下載安裝功能
"""

import html as _html
import platform
import re
import sys
import tempfile
import time
from pathlib import Path

import markdown as _markdown

from . import (
    HTTPUtils,
    PathUtils,
    RuntimePaths,
    SubprocessUtils,
    UIUtils,
    get_logger,
)

logger = get_logger().bind(component="UpdateChecker")


class UpdateChecker:
    _GITHUB_API = "https://api.github.com"

    @staticmethod
    def _parse_version(version_str: str) -> tuple[int, ...] | None:
        """解析版本字串為數字元組（使用簡單的標準方法）"""
        try:
            if not isinstance(version_str, str) or not version_str.strip():
                logger.warning(f"無效的版本字串，version_str={version_str!r}")
                return None
            clean = version_str.strip().lstrip("vV")
            version_part = clean.split("-")[0].split("+")[0]
            return tuple(int(x) for x in version_part.split(".") if x.isdigit())
        except ValueError:
            logger.warning(f"版本字串解析失敗，version_str={version_str!r}")
            return None

    @staticmethod
    def _get_latest_release(owner: str, repo: str) -> dict:
        url = f"{UpdateChecker._GITHUB_API}/repos/{owner}/{repo}/releases"
        data = HTTPUtils.get_json(url, timeout=15)
        if not data:
            return {}

        if isinstance(data, dict):
            return {}

        for rel in data:
            try:
                if rel and not rel.get("draft") and not rel.get("prerelease"):
                    return rel
            except Exception as e:
                logger.debug(f"檢查 release 資料時發生錯誤: {e}")
                continue
        return {}

    @staticmethod
    def _choose_installer_asset(release: dict) -> dict:
        assets = release.get("assets") or []
        exe_assets = []
        for a in assets:
            try:
                name = (a.get("name") or "").lower()
                if name.endswith(".exe") and a.get("browser_download_url"):
                    exe_assets.append(a)
            except Exception as e:
                logger.debug(f"檢查 asset 資料時發生錯誤: {e}")
                continue
        if not exe_assets:
            return {}

        for a in exe_assets:
            name = (a.get("name") or "").lower()
            if "setup" in name or "installer" in name:
                return a
        return exe_assets[0]

    @staticmethod
    def _launch_installer(installer_path: Path, parent=None) -> None:
        """啟動安裝程式

        Args:
            installer_path: 安裝程式檔案路徑
            parent: 父視窗物件，用於在主執行緒顯示 UI 對話框
        """
        try:
            # 確保安裝程式位於預期的暫存目錄中，以避免從任意位置執行惡意程式
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
                confirm = UIUtils.call_on_ui(
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

                # 在 Windows 上使用進程分離標誌，避免安裝程式與主程式耦合
                # 這樣可以防止主程式退出時留下孤兒進程
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                creation_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

                # 僅在 Windows 平台傳遞 creationflags
                process = SubprocessUtils.popen_checked(
                    [str(resolved_path)],
                    stdin=SubprocessUtils.DEVNULL,
                    stdout=SubprocessUtils.DEVNULL,
                    stderr=SubprocessUtils.DEVNULL,
                    close_fds=True,
                    **({"creationflags": creation_flags} if platform.system() == "Windows" else {}),
                )

                # 確認進程已啟動
                time.sleep(0.5)
                returncode = process.poll()
                if returncode is not None:
                    # installer 可能啟動子進程後自行退出（正常行為），僅在非 0 退出碼時視為失敗
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

                parent.after(delay_ms, _close)
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

            # 忽略 "New Contributors" 或 "Full Changelog" 區塊
            if "new contributors" in l_lower or "full changelog" in l_lower:
                ignoring = True
                if "full changelog" in l_lower:
                    break
                continue

            if ignoring:
                # 若遇到新的標題 (## ...) 且看起來像功能區塊，則停止忽略
                if l_strip.startswith("#"):
                    ignoring = False
                else:
                    continue

            # 移除 GitHub 自動生成的 PR 資訊: "by @user in https://..."
            clean_line = re.sub(r"\s+by\s+@[\w\-]+", "", line)
            clean_line = re.sub(r"\s+in\s+https://\S+", "", clean_line)

            if not clean_line.strip():
                continue

            kept_lines.append(clean_line)

        text = "\n".join(kept_lines)
        try:
            html = _markdown.markdown(text)
            text_only = re.sub(r"<[^<]+?>", "", html)
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
        current_version: str,
        owner: str,
        repo: str,
        show_up_to_date_message: bool = True,
        parent=None,
    ) -> None:
        def _work() -> None:
            # 追踪所有需要清理的暫存檔案和目錄
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
                                import shutil

                                shutil.rmtree(temp_path, ignore_errors=True)
                                logger.debug(f"已刪除暫存目錄: {temp_path}")
                    except Exception as e:
                        logger.debug(f"清理暫存檔案時發生錯誤 {temp_path}: {e}")

            try:
                logger.info(f"開始檢查更新... (目前版本: {current_version})")
                latest = UpdateChecker._get_latest_release(owner, repo)
                if not latest:
                    logger.info("無法從 GitHub 取得最新版本資訊")
                    if show_up_to_date_message:
                        UIUtils.call_on_ui(
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

                # 比較版本
                if latest_ver <= current_ver:
                    logger.info("目前已是最新版本")
                    if show_up_to_date_message:
                        UIUtils.call_on_ui(
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

                # 使用清理後的釋出說明
                rendered = UpdateChecker._clean_release_notes(body)

                html_url = latest.get("html_url")

                msg = f"發現新版本：{name}\n目前版本：{current_version}\n\n釋出說明：\n{rendered}\n\n是否下載並安裝？"
                result = UIUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.ask_yes_no_cancel(
                        "更新可用",
                        msg,
                        parent=parent,
                        show_cancel=False,
                        topmost=True,
                    ),
                )
                if not result:
                    return

                logger.info("使用者確認更新，準備下載...")

                # 若為可攜式，優先尋找 portable zip asset
                asset = None
                if RuntimePaths.is_portable_mode():
                    assets = latest.get("assets") or []
                    for a in assets:
                        try:
                            name_l = (a.get("name") or "").lower()
                            if name_l.endswith(".zip") and "portable" in name_l and a.get("browser_download_url"):
                                asset = a
                                break
                        except Exception as e:
                            logger.debug(f"檢查可攜式資源時發生錯誤，跳過此資源: {e}")
                            continue

                # 若尚未選到，使用原有的 exe 選擇邏輯
                if not asset:
                    asset = UpdateChecker._choose_installer_asset(latest)

                if not asset:
                    UIUtils.call_on_ui(
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
                    UIUtils.call_on_ui(
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

                # Helper: 嘗試從 release 的 assets 或 body 解析出對應 asset 的 checksum
                def _parse_checksum_text(text: str, asset_name: str) -> tuple[str, str] | None:
                    asset_base = Path(asset_name).name
                    asset_base_lower = asset_base.lower()
                    for line in (text or "").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        line_lower = line.lower()
                        parts = line.split()
                        for token in parts:
                            if re.fullmatch(r"[0-9a-fA-F]{64}", token) and asset_base_lower in line_lower:
                                return ("sha256", token.lower())
                            if re.fullmatch(r"[0-9a-fA-F]{128}", token) and asset_base_lower in line_lower:
                                return ("sha512", token.lower())
                    return None

                def _fetch_checksum_for_asset(release: dict, asset_name: str) -> tuple[str, str] | None:
                    """
                    獲取 asset 的 checksum

                    優先級（從最安全到次安全）：
                    1. 優先從 release body 中讀取（純線上，不下載任何檔案）
                    2. 其次從 assets 中下載 checksum 檔案（下載小檔案）
                    3. 如果都沒有，返回 None（拒絕下載主檔案）
                    """
                    try:
                        # ===== 優先級 1: 從 release body 中查找 checksum（純線上，不下載） =====
                        logger.debug(
                            f"[SHA256 查詢] 方法 1/2：從 release body 中查找 {asset_name} 的 checksum（線上查詢）..."
                        )
                        body = release.get("body") or ""
                        c = _parse_checksum_text(body, asset_name)
                        if c:
                            logger.info(
                                f"[SHA256 查詢成功] ✓ 已從 release body 中取得 checksum（{c[0]}），無需下載額外檔案"
                            )
                            return c

                        logger.debug(
                            "[SHA256 查詢] release body 中未找到 checksum，嘗試從 assets 中下載 checksum 檔案..."
                        )

                        # ===== 優先級 2: 從 assets 中下載 checksum 檔案 =====
                        assets = release.get("assets") or []
                        checksum_files = [
                            a
                            for a in assets
                            if (a.get("name") or "")
                            .lower()
                            .endswith((".sha256", ".sha256sum", ".sha512", ".sha512sum"))
                        ]

                        if checksum_files:
                            logger.debug(
                                f"[SHA256 查詢] 方法 2/2：在 release assets 中找到 {len(checksum_files)} 個 checksum 檔案"
                            )
                            for a in checksum_files:
                                try:
                                    an = a.get("name") or ""
                                    logger.debug(f"[SHA256 查詢] 嘗試下載 checksum 檔案: {an}")
                                    with tempfile.NamedTemporaryFile(
                                        delete=False, prefix="msm_chk_", suffix=".txt"
                                    ) as tf:
                                        tfpath = tf.name
                                    # 記錄 checksum 檔案以便後續清理
                                    temp_files_to_cleanup.append(Path(tfpath))
                                    if HTTPUtils.download_file(a.get("browser_download_url"), tfpath):
                                        txt = Path(tfpath).read_text(encoding="utf-8", errors="ignore")
                                        c = _parse_checksum_text(txt, asset_name)
                                        if c:
                                            logger.info(
                                                f"[SHA256 查詢成功] ✓ 已從 asset ({an}) 中取得 checksum（{c[0]}）"
                                            )
                                            return c
                                        logger.debug(
                                            f"[SHA256 查詢] 檔案 {an} 內容已下載，但未找到 {asset_name} 的 checksum"
                                        )
                                    else:
                                        logger.debug(f"[SHA256 查詢] 下載 {an} 失敗")
                                except Exception as e:
                                    logger.debug(
                                        f"[SHA256 查詢] 檢查 checksum 檔案 {a.get('name')} 時發生錯誤，嘗試下一個: {e}"
                                    )
                                    continue
                        else:
                            logger.debug("[SHA256 查詢] 在 release assets 中找不到任何 checksum 檔案")

                        # ===== 所有方法都失敗 =====
                        logger.warning(f"[SHA256 查詢失敗] 無法透過任何方式取得 {asset_name} 的 checksum")
                        logger.warning(
                            "[SHA256 查詢失敗] 詳情：Release body 中無 checksum，Assets 中無有效的 checksum 檔案或無法解析"
                        )
                        return None
                    except Exception as e:
                        logger.exception(f"[SHA256 查詢錯誤] 在查詢過程中發生未預期的錯誤: {e}")
                    return None

                def _verify_file_checksum(path: Path, algorithm: str, hex_checksum: str) -> bool:
                    checksum = PathUtils.calculate_checksum(path, algorithm)
                    return checksum == hex_checksum.lower() if checksum else False

                # 如果是可攜式更新（asset 為 portable zip），採用 ZIP 解壓套用流程
                if RuntimePaths.is_portable_mode() and download_url and str(download_url).lower().endswith(".zip"):
                    if not UIUtils.call_on_ui(
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

                    # ===== 步驟 1: 線上確認 SHA256 是否存在（不下載主檔案） =====
                    logger.info("[安全檢查] 正在線上查詢更新檔的 SHA256 驗證資訊...")
                    try:
                        chk = _fetch_checksum_for_asset(latest, asset.get("name") or "")
                        if not chk:
                            logger.error("[安全檢查失敗] 未找到 SHA256，拒絕下載未經驗證的檔案")
                            UIUtils.call_on_ui(
                                parent,
                                lambda: UIUtils.show_error(
                                    "缺少 SHA256 驗證資訊",
                                    "無法從 GitHub Release 中取得此更新檔的 SHA256 驗證資訊。\n\n為了您的系統安全：\n❌ 將不會下載任何檔案\n❌ 更新已取消\n\n建議聯絡開發者確認 Release 是否包含 SHA256 資訊。",
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
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "安全驗證錯誤",
                                "在線上查詢 SHA256 驗證資訊時發生錯誤。\n\n為了您的系統安全：\n❌ 將不會下載任何檔案\n❌ 更新已取消",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return

                    # ===== 步驟 2: 下載主檔案（已確認有 SHA256 可驗證） =====
                    logger.info("[下載階段] 開始下載可攜式更新檔...")
                    with tempfile.NamedTemporaryFile(delete=False, prefix="msm_portable_", suffix=".zip") as tmpf:
                        tmp_zip_path = tmpf.name
                    temp_files_to_cleanup.append(Path(tmp_zip_path))

                    if not HTTPUtils.download_file(download_url, tmp_zip_path):
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error("下載失敗", "無法下載可攜式更新。", parent=parent, topmost=True),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return

                    # ===== 步驟 3: 立即驗證下載檔案的 SHA256 =====
                    logger.info("[驗證階段] 正在計算並驗證下載檔案的 SHA256...")
                    logger.info(f"[驗證階段] 預期 SHA256: {expected_checksum}")
                    ok = _verify_file_checksum(Path(tmp_zip_path), alg, expected_checksum)
                    if not ok:
                        logger.error(f"[驗證失敗] SHA256 不符合！檔案: {asset.get('name')}")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "SHA256 驗證失敗",
                                "下載的檔案 SHA256 驗證失敗！\n\n可能原因：\n• 下載過程中檔案損壞\n• 檔案被惡意篡改\n• 網路傳輸錯誤\n\n為了您的安全：\n✓ 已立即刪除下載的檔案\n✓ 更新已取消\n\n請稍後重試，或手動從 GitHub 下載。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    logger.info(f"[驗證通過] ✓ SHA256 驗證成功：{asset.get('name')}")

                    # 解壓到暫存資料夾
                    extracted_dir = Path(tempfile.mkdtemp(prefix="msm_portable_extracted_"))
                    temp_files_to_cleanup.append(extracted_dir)

                    try:
                        PathUtils.safe_extract_zip(Path(tmp_zip_path), extracted_dir)
                    except Exception as e:
                        logger.exception(f"解壓更新檔失敗: {e}")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "解壓失敗", "無法解壓下載的更新檔。", parent=parent, topmost=True
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return

                    # 備份整個原始目錄與 .config/.log
                    base = RuntimePaths._get_portable_base_dir()
                    cfg = base / ".config"
                    lg = base / ".log"

                    # 通知使用者準備關閉程式進行更新
                    UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "更新中",
                            "正在應用更新，程式將在 3 秒後關閉...",
                            parent=parent,
                            topmost=True,
                        ),
                    )

                    logger.info("通知使用者程式將關閉進行更新")

                    backup_root = Path(tempfile.mkdtemp(prefix="msm_portable_backup_"))
                    logger.info(f"開始備份原始目錄與配置: {backup_root}")

                    try:
                        # 備份整個原始目錄（不包括 .config/.log/.portable）
                        backup_dir = backup_root / "original"
                        PathUtils.copy_dir(
                            base,
                            backup_dir,
                            ignore_patterns=[".config", ".log", ".portable"],
                        )

                        # 單獨備份 .config 與 .log
                        if cfg.exists():
                            PathUtils.copy_dir(cfg, backup_root / ".config")
                            logger.info("已備份 .config")
                        if lg.exists():
                            PathUtils.copy_dir(lg, backup_root / ".log")
                            logger.info("已備份 .log")
                    except Exception as e:
                        error_msg = str(e)
                        logger.exception(f"備份失敗: {error_msg}")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "備份失敗",
                                f"無法備份現有配置，停止更新以確保安全。\n{error_msg}",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        return

                    # 建立套用更新的批次檔，等待主程式退出後執行更新
                    apply_bat = Path(tempfile.gettempdir()) / f"msm_apply_update_{int(time.time())}.bat"

                    # 驗證路徑安全性：確保 extracted_dir 和 backup_root 在暫存目錄內
                    try:
                        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
                        extracted_dir_resolved = extracted_dir.resolve(strict=True)
                        backup_root_resolved = backup_root.resolve(strict=True)
                        base.resolve(strict=True)

                        if not PathUtils.is_path_within(temp_root, extracted_dir_resolved, strict=True):
                            logger.error(f"解壓目錄不在暫存目錄中，已取消更新：{extracted_dir_resolved}")
                            UIUtils.call_on_ui(
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
                            UIUtils.call_on_ui(
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
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "錯誤",
                                "路徑驗證失敗，已取消更新。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return

                    src = str(extracted_dir).replace("/", "\\")
                    dst = str(base).replace("/", "\\")
                    backup_path = str(backup_root).replace("/", "\\")

                    # 檢查解壓後的結構：如果第一層只有 MinecraftServerManager 資料夾，則進入它
                    extracted_items = list(extracted_dir.iterdir())
                    if (
                        len(extracted_items) == 1
                        and extracted_items[0].is_dir()
                        and extracted_items[0].name == "MinecraftServerManager"
                    ):
                        src = str(extracted_items[0]).replace("/", "\\")
                        logger.info(f"檢測到嵌套資料夾，調整源路徑為: {src}")

                    bat = (
                        "@echo off\n"
                        "chcp 65001 >nul\n"
                        "setlocal enabledelayedexpansion\n"
                        "REM 等待主程式完全退出（檢查20次，每次等待1秒）\n"
                        'set "count=0"\n'
                        ":wait_loop\n"
                        'tasklist /FI "IMAGENAME eq MinecraftServerManager.exe" 2>nul | find /I "MinecraftServerManager.exe" >nul\n'
                        "if %ERRORLEVEL%==0 (\n"
                        "    if !count! lss 20 (\n"
                        "        set /a count=!count!+1\n"
                        "        timeout /t 1 /nobreak >nul\n"
                        "        goto wait_loop\n"
                        "    )\n"
                        ")\n"
                        "REM 給予額外的時間確保所有檔案都解鎖\n"
                        "timeout /t 3 /nobreak >nul\n"
                        f"REM 刪除整個原始目錄\n"
                        f'for /d %%I in ("{dst}\\*") do (\n'
                        f'    rmdir /s /q "%%I" 2>nul\n'
                        f")\n"
                        f'for %%I in ("{dst}\\*") do (\n'
                        f'    del /q "%%I" 2>nul\n'
                        f")\n"
                        f"timeout /t 1 /nobreak >nul\n"
                        f"REM 複製新版本檔案（使用 PowerShell 以獲得更好的錯誤處理）\n"
                        f'powershell -Command "try {{ Copy-Item -LiteralPath "{src}\\*" -Destination "{dst}" -Recurse -Force -ErrorAction Stop }} catch {{ exit 1 }}"\n'
                        f"if %ERRORLEVEL% neq 0 (\n"
                        f"    echo 複製失敗，嘗試使用 xcopy...\n"
                        f'    xcopy "{src}\\*" "{dst}\\" /E /Y /I /R\n'
                        f")\n"
                        f"REM 恢復備份的 .config 與 .log\n"
                        f'if exist "{backup_path}\\.config" (\n'
                        f'    xcopy "{backup_path}\\.config\\*" "{dst}\\.config\\" /E /Y /I /R 2>nul\n'
                        f")\n"
                        f'if exist "{backup_path}\\.log" (\n'
                        f'    xcopy "{backup_path}\\.log\\*" "{dst}\\.log\\" /E /Y /I /R 2>nul\n'
                        f")\n"
                        f"REM 恢復或建立 .portable 標記\n"
                        f'if not exist "{dst}\\.portable" (\n'
                        f'    echo. > "{dst}\\.portable"\n'
                        f'    attrib +h "{dst}\\.portable" 2>nul\n'
                        f")\n"
                        f"REM 啟動新版本\n"
                        f"timeout /t 2 /nobreak >nul\n"
                        f'start "" "{dst}\\MinecraftServerManager.exe"\n'
                        f"REM 刪除備份（更新成功後）\n"
                        f"timeout /t 5 /nobreak >nul\n"
                        f'rmdir /s /q "{backup_path}" 2>nul\n'
                        f"REM 自刪更新批次檔\n"
                        f'del /f /q "%~f0" 2>nul\n'
                        "endlocal\n"
                        "exit /b 0\n"
                    )
                    try:
                        apply_bat.write_text(bat, encoding="utf-8")
                    except Exception:
                        logger.exception("寫入批次檔失敗")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error("錯誤", "無法建立套用更新的腳本。", parent=parent, topmost=True),
                        )
                        return

                    try:
                        # 驗證批次檔路徑必須位於系統暫存資料夾內，避免被惡意覆寫為其他位置的腳本
                        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
                        apply_bat_resolved = apply_bat.resolve(strict=True)
                        if not PathUtils.is_path_within(temp_root, apply_bat_resolved, strict=True):
                            logger.error(
                                "套用更新批次檔的路徑不在暫存目錄中，已拒絕執行。",
                                apply_bat=str(apply_bat_resolved),
                                temp_root=str(temp_root),
                            )
                            UIUtils.call_on_ui(
                                parent,
                                lambda: UIUtils.show_error(
                                    "錯誤",
                                    "偵測到異常的更新腳本路徑，已取消自動更新以確保安全。",
                                    parent=parent,
                                    topmost=True,
                                ),
                            )
                            return

                        cmd_exe = PathUtils.find_executable("cmd.exe") or "C:\\Windows\\System32\\cmd.exe"
                        # 安全修復：使用 SubprocessUtils.popen_checked 替代 subprocess.Popen
                        SubprocessUtils.popen_checked(
                            [cmd_exe, "/c", "start", "", str(apply_bat_resolved)],
                            stdin=SubprocessUtils.DEVNULL,
                            stdout=SubprocessUtils.DEVNULL,
                            stderr=SubprocessUtils.DEVNULL,
                            close_fds=True,
                        )
                    except Exception:
                        logger.exception("啟動套用批次檔失敗")
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return

                    logger.info("更新批次已啟動，準備關閉程式以進行更新")
                    # 批次檔會在程式關閉後處理更新，因此在這裡清理下載的暫存檔
                    _cleanup_temp_files(temp_files_to_cleanup)

                    # 可攜式更新：不要啟動內建重啟流程，直接退出，交由批次檔等待並重啟
                    time.sleep(close_delay_seconds)
                    UpdateChecker._graceful_exit(parent)
                    return

                # 非可攜式或找不到 portable zip，沿用原有 installer.exe 流程

                # ===== 步驟 1: 線上確認 SHA256 是否存在（不下載主檔案） =====
                logger.info("[安全檢查] 正在線上查詢安裝程式的 SHA256 驗證資訊...")
                try:
                    chk = _fetch_checksum_for_asset(latest, asset.get("name") or "")
                    if not chk:
                        logger.error("[安全檢查失敗] 未找到 SHA256，拒絕下載未經驗證的檔案")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "缺少 SHA256 驗證資訊",
                                "無法從 GitHub Release 中取得此安裝程式的 SHA256 驗證資訊。\n\n為了您的系統安全：\n❌ 將不會下載任何檔案\n❌ 更新已取消\n\n建議聯絡開發者確認 Release 是否包含 SHA256 資訊。",
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
                    UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_error(
                            "安全驗證錯誤",
                            "在線上查詢 SHA256 驗證資訊時發生錯誤。\n\n為了您的系統安全：\n❌ 將不會下載任何檔案\n❌ 更新已取消",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    _cleanup_temp_files(temp_files_to_cleanup)
                    return

                # ===== 步驟 2: 下載安裝程式（已確認有 SHA256 可驗證） =====
                logger.info("[下載階段] 開始下載安裝程式...")
                with tempfile.NamedTemporaryFile(delete=False, prefix="msm_update_", suffix=".exe") as tmp:
                    temp_path = tmp.name
                dest = Path(temp_path)
                temp_files_to_cleanup.append(dest)
                if HTTPUtils.download_file(download_url, str(dest)):
                    # ===== 步驟 3: 立即驗證下載檔案的 SHA256 =====
                    logger.info("[驗證階段] 正在計算並驗證下載檔案的 SHA256...")
                    logger.info(f"[驗證階段] 預期 SHA256: {expected_checksum}")
                    ok = _verify_file_checksum(dest, alg, expected_checksum)
                    if not ok:
                        logger.error(f"[驗證失敗] SHA256 不符合！檔案: {asset.get('name')}")
                        UIUtils.call_on_ui(
                            parent,
                            lambda: UIUtils.show_error(
                                "SHA256 驗證失敗",
                                "下載的檔案 SHA256 驗證失敗！\n\n可能原因：\n• 下載過程中檔案損壞\n• 檔案被惡意篡改\n• 網路傳輸錯誤\n\n為了您的安全：\n✓ 已立即刪除下載的檔案\n✓ 更新已取消\n\n請稍後重試，或手動從 GitHub 下載。",
                                parent=parent,
                                topmost=True,
                            ),
                        )
                        _cleanup_temp_files(temp_files_to_cleanup)
                        return
                    logger.info(f"[驗證通過] ✓ SHA256 驗證成功：{asset.get('name')}")

                    # 啟動安裝程式（獨立進程）
                    UpdateChecker._launch_installer(dest, parent=parent)
                    logger.info("安裝程式已啟動（獨立進程）")
                    if dest in temp_files_to_cleanup:
                        temp_files_to_cleanup.remove(dest)
                    _cleanup_temp_files(temp_files_to_cleanup)

                    # 顯示訊息並等待使用者確認
                    UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_info(
                            "更新準備就緒",
                            "安裝程式已啟動。\n\n程式將在關閉此訊息後結束。\n請依安裝程式指示完成更新。",
                            parent=parent,
                            topmost=True,
                        ),
                    )

                    # 給予安裝程式充足的啟動時間
                    time.sleep(2)
                    logger.info("準備關閉當前程式以完成更新")
                    UpdateChecker._graceful_exit(parent)
                else:
                    UIUtils.call_on_ui(
                        parent,
                        lambda: UIUtils.show_error(
                            "下載失敗",
                            "無法下載安裝檔，請稍後再試。",
                            parent=parent,
                            topmost=True,
                        ),
                    )
                    _cleanup_temp_files(temp_files_to_cleanup)
            except Exception as e:
                logger.exception(f"更新檢查失敗: {e}")
                error_msg = str(e)
                UIUtils.call_on_ui(
                    parent,
                    lambda: UIUtils.show_error(
                        "更新檢查失敗",
                        f"無法完成更新檢查或下載：{error_msg}",
                        parent=parent,
                        topmost=True,
                    ),
                )
                _cleanup_temp_files(temp_files_to_cleanup)

        UIUtils.run_async(_work)
