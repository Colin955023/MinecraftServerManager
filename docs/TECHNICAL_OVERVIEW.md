# 技術手冊

## 技術棧

| 類別 | 工具 |
|---|---|
| 執行環境 | Python `>=3.14,<3.15`、Windows 10／11 |
| GUI | PySide6、PySide6-Fluent-Widgets |
| 網路／資料 | httpx、orjson、packaging、defusedxml |
| 系統／日誌 | psutil、Python `logging` |
| 打包 | Nuitka onefile |
| 品質 | pytest-cov、Ruff、Mypy、Pylint、Bandit、Vulture、detect-secrets、自訂匯入邊界檢查 |

相依套件與最低版本以 `pyproject.toml`、鎖定版本以 `uv.lock` 為準。

## 架構

```text
src/main.py
└─ ui/core_frames/main_window.py        唯一 production composition root
   ├─ core/server/                      建立、匯入、檢查、執行、屬性、備份
   ├─ core/mods/                        掃描、安裝、Provider、Modrinth、規劃
   ├─ core/loader/                      載入器版本、安裝與適配
   ├─ ui/core_frames|dialogs|mods|...   Qt／Fluent UI adapters
   ├─ models/mod_models.py              模組共享領域資料
   ├─ models/server_models.py           伺服器共享領域資料
   └─ utils/                            檔案、網路、Java、日誌、執行期工具
```

依賴方向由 `scripts/check_import_boundaries.py` 對全部 `src/**/*.py` 強制：

```text
ui → core → models → utils
```

### 主要 owner

| 領域 | 唯一 owner／外部 seam |
|---|---|
| 建立伺服器 | `CreateServerJourney`：plan → 確認同一 plan → execute |
| 伺服器內容 | `ServerInspector.inspect()`：版本、載入器、EULA、缺檔、啟動目標 |
| 執行中程序 | `ServerRuntime`：process、PID、輸出、狀態、命令、停止與清理 |
| 伺服器屬性 | `ServerPropertiesStore`：`server.properties`、revision conflict、原子提交 |
| 模組規劃 | application-scoped `ModPlanning`：相容性、遞迴依賴、本地更新 |
| 模組 UI 狀態 | `ModManagementSession`；各 Presenter 擁有自己的 widget／view state |
| Review | `ModReviewWorkflow`、immutable snapshot、`ReviewExecutionHandoff` |
| UI 背景工作 | `UIWorkScope` |

## 匯入邊界

自訂邊界只掃描 `src/`。測試可深層匯入，以直接測試或替換 `src` implementation dependency；測試引用不會使未被 production 使用的 facade export 合法化。

- `src/` 跨頂層 package 必須從 `src.core`、`src.models`、`src.ui`、`src.utils` 匯入。
- 同一 feature 目錄的內部協作使用單層相對匯入；禁止父層 traversal。
- 只允許 `src/__init__.py` 與 `src/{core,models,ui,utils}/__init__.py`。
- facade 使用 `lazy_exports`，只能匯出自己頂層 package 內且有 `src/` runtime consumer 的符號。
- `src.models` 只公開共享領域資料；UI／workflow internal 型別留在 owner。

執行：

```bat
uv run scripts\check_import_boundaries.py
```

## 目錄職責

### `src/core/server/`

| 檔案 | 職責 |
|---|---|
| `server_crud.py` | 伺服器登錄、設定檔與刪除 tombstone 背景清理 |
| `server_creation.py` | 交易式建立、整體進度映射與補償 |
| `server_import.py` | 資料夾／ZIP 匯入、探索、已管理項目計數與重新偵測 |
| `server_inspector.py` | 唯讀內容檢查 |
| `server_runtime.py` | 統一啟動與首次初始化生命週期；協調備份、還原、刪除期間的維護保留 |
| `server_output_history.py` | 安全讀取受限大小的輸出尾端，保留重複訊息與截斷狀態 |
| `server_properties.py` | `server.properties` 唯一真相來源 |
| `server_backup.py` | 原子 ZIP 備份、交易式快照還原與失敗回滾 |

### `src/core/mods/`

| 檔案 | 職責 |
|---|---|
| `mod_manager.py` | 掃描、安裝與 provider orchestration |
| `local_mod_scanner.py` | JAR metadata 與快取回填 |
| `mod_file_installer.py` | 下載、安裝、替換、回滾、刪除 |
| `provider_identity.py` | provider 身分與生命週期 |
| `modrinth_http.py` | Modrinth HTTP 查詢與 `ModrinthHttpAdapter` |
| `dependency_planner_facade.py` | `ModPlanning` 唯一 use-case interface |
| `compatibility_analyzer.py` | 內部純相容性分析 |
| `mod_planning_ports.py` | loader rules port 與 production adapter |
| `mod_provider_port.py` | provider 窄 port |

### `src/core/loader/`

| 檔案 | 職責 |
|---|---|
| `loader_manager.py` | 載入器中繼資料、版本解析與查詢 |
| `loader_installer.py` | 載入器安裝執行、文字進度解析／估算與檔案配置 |
| `loader_adapters.py` | 載入器外部資料來源適配 |

### `src/ui/`

- `core_frames/`：主視窗、建立、管理、偏好與導航。
- `dialogs/`：建立確認、屬性、JVM、還原及進度對話框。
- `mods/`：具名 feature、Session、Review workflow、install executor、tree projection。
- `services/`：管理頁狀態計算與跨頁工作協調。
- `support/`：Fluent 主題、UI tokens、狀態、`UIUtils`、`UIWorkScope`。
- `windows/`：伺服器監控。

`ModManagementFrame` 只負責根組裝與生命週期，不代理 feature command。`review_dependency.py`、`review_details.py`、`review_formatting.py`、`review_grouping.py`、`review_prompts.py`、`review_selection.py`、`review_snapshot_store.py` 與 `review_state.py` 是內部 implementation；外部 seam 維持 `review_workflow.py` 與 `review_contracts.py`。

### `src/utils/`

- `core_utils/`：原子寫入、路徑、雜湊、例外、日誌、單位、版本。
- `network_utils/`：集中 HTTP timeout、retry、URL 驗證及一般回應內容上限；URL 靜態政策檢查不觸發 DNS，實際 request attempt 才解析一次並固定公開 IP；原始 HTTPS origin 各自使用隔離的 connection pool，保留 Host/SNI 並避免不同 hostname 因共用 IP 而誤用同一連線。一般 request 使用單一 private retry state machine，完整檔案下載則由完整下載交易擁有唯一 retry budget，避免開流與串流層重試乘積化。
- `java_support/`：Java 偵測與 winget 安裝。
- `runtime_utils/`：路徑、設定、背景工作、subprocess、系統狀態。
- `mod_utils/`：下載政策、metadata、語意與版本過濾。
- `server_utils/`：記憶體、啟動命令、版本語意與共用伺服器名稱安全政策。
- `update_utils/`：更新資料解析。

## 進度、主題與刪除交易

- `ProgressEvent` 的 `overall_percent` 是建立伺服器 UI 的穩定整體進度來源。下載階段優先使用實際 byte／unit 比例；Java Loader installer 若只提供 `stage`／`message` 文字，`InstallerProgressTracker` 依已知階段做**估算**，不可視為安裝器官方百分比。明確 `%` 或 `x/y` 輸出仍優先採用。`ProgressDialog` 一旦取得可判定進度即維持 determinate 模式，並拒絕延遲事件造成百分比倒退。
- 共用 Fluent modal 與監控 surface 由 `themed_surface_stylesheet()` 依 `Colors` token 套用背景、主要／次要文字及邊框；不要在個別 Label 只覆寫 transparent background 而遺失主題文字色。
- Qt 視窗圖示由 `qt_runtime.apply_window_icon()` 統一處理。開發環境讀取 `assets/icon.ico`；Nuitka 封裝環境在 `QApplication.windowIcon()` 缺失時從目前 EXE 的 Windows icon resource 取得，再同步至主視窗、modal、監控視窗與 Fluent title bar。
- 刪除伺服器的同步 commit point 是「原目錄改名為 `.msm-delete-*` tombstone + 原子移除登錄」。commit 成功後才回報列表已移除，實體遞迴刪除在背景執行並對暫時性檔案鎖做有限重試。`ServerCRUD` 是刪除 tombstone 的唯一恢復 owner：重新啟動時，若 marker 對應的伺服器仍在登錄且原路徑消失，視為尚未 commit 並 fail-safe 還原；若已不在登錄，才排程背景清理。其他 transaction owner 不可直接刪除 `.msm-delete-*`。

## 重要實作規則

- JSON／文字寫入使用原子寫入；不要直接覆寫正式檔。
- GUI 可見控制項使用 QFluentWidgets；PySide6 保留基礎設施，檔案選擇器集中於 `UIUtils`。
- UI 背景工作經 `UIWorkScope`；主視窗關閉時保存設定、停止計時器，以非阻塞流程停止 runtime 與背景工作，再關閉其餘視窗。
- `server.properties` 不複製到 `ServerConfig`。
- production 與 tests 應驗證同一外部 seam；不得為測試新增 production API。
- 測試必須全自動且不得觸發真實網路、互動視窗或外部程式；必要檔案只能建立於 pytest `tmp_path` 並在測試後清除。

## 開發命令

```bat
uv sync
uv run python -m src.main

uv sync --group test
uv run pytest -q --cov=src --cov-branch --cov-report=term-missing --cov-report=xml:coverage.xml

scripts\format_lint_fix_gate.bat
uv run report\comprehensive_report.py
```

### Nuitka 建置

正式輸出使用 `scripts\build_nuitka.ps1` 建立 onefile 執行檔。腳本會先同步 build 群組、拒絕在輸出執行檔仍執行時覆寫、產生 `report\nuitka-compilation-report.xml`，並驗證 onefile 狀態、必要的 `LICENSE` 及禁止的 Qt platform DLL。建置報告若需供工具解析，請以 UTF-8 位元組讀取後再交給 XML parser，避免 XML 宣告編碼與 PowerShell 字串轉換不一致。

```bat
powershell -ExecutionPolicy Bypass -File scripts\build_nuitka.ps1
```

`dist\<repository>.exe` 是發佈檔；`dist\main.dist` 只作建置檢查與問題診斷，不應直接當作安裝內容。

onefile 預設使用 Nuitka 的版本化快取規格 `{CACHE_DIR}/Programs/MinecraftServerManager/{VERSION}`，Windows 實際位置為 `%LOCALAPPDATA%\Programs\MinecraftServerManager\<版本>`。新版本完成啟動後會清理舊版本目錄；若舊版本仍被鎖定則保留至下次啟動再清理。

使用方式見 [USER_GUIDE.md](USER_GUIDE.md)。
