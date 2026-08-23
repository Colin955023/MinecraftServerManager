# Changelog

## v1.8.0 - 2026-08-23

### 新增
- **交易式伺服器建立與匯入流程**：新增 `server_creation.py`（`CreateServerJourney`）與 `server_import.py`，支援 Plan-Execute 兩階段建立、伺服器批次探索、重新偵測以及建立前參數與指令核對對話框（`server_creation_confirm_dialog.py`）。
- **模組狀態機與審查工作流程體系**：新增 `ModManagementSession` 作為本地、線上與佇列狀態的單一資料來源，並將模組安裝審查流程拆分為模組化工作流程（`review_workflow.py`、`review_contracts.py`、`review_grouping.py`、`review_dependency.py` 等）。
- **Provider Metadata 與身分快取管理**：新增 `provider_identity.py` 與 `modrinth_provider_adapter.py`，統一管理模組提供者身分解析、雜湊對應與生命週期快取。
- **集中化網路客戶端與背景協調**：新增 `http_client.py` 整合逾時、重試與連線集區管理；新增 `UIWorkScope` 統一控管 UI 背景非同步任務生命週期；新增 `status_button.py` 狀態按鈕元件。
- **JVM 參數自訂與最佳化對話框**：新增獨立的 `jvm_args_dialog.py`，提供 JVM 參數自訂、記憶體配置建議與語法驗證。
- **擴充自動化測試**：新增交易式建立與匯入、模組 Session 與 Review 工作流程、Provider 身分解析、HTTP Client 下載以及 UI 回歸等測試套件。

### 調整
- **UI 架構模組化與目錄分層**：重組 `src/ui/` 目錄為 `core_frames/`（主頁面框架）、`dialogs/`（對話框與彈窗）、`services/`（如 `application_shell.py`）、`windows/`（獨立監控視窗），並以 `HostBound` 委派模式解耦 View 與狀態操作。
- **模組搜尋與相容性核心遷移**：將 Modrinth 搜尋服務與相容性分析模組（`modrinth_service.py`、`compatibility_analyzer.py`、`dependency_planner_facade.py` 等）由 UI 層遷入 `src/core/mods/`。
- **底層工具、日誌與例外處理簡化**：以 `exceptions.py` 取代 `exception_utils.py`；全面改採 `loguru` 非同步分級日誌與 `psutil` 處理程序監控；全面移除舊版 `http_utils.py`、`task_utils.py`、`mod_provider_resolver.py`，並大幅精簡 `path_utils.py`、`system_utils.py` 與 `server_detection_utils.py`。
- **QFluentWidgets 原生元件全面導入**：全面移除舊有相容層與手動 QSS 計算，改採 QFluentWidgets 原生元件與主題切換機制。

### 修正
- 修正伺服器建立與匯入過程中的交易回滾機制與路徑安全驗證。
- 修正模組依賴解析與 Provider 身分匹配中的快取一致性與型別轉換異常。
- 修復背景執行緒與 UI 元件互動時可能產生的競爭條件與例外捕捉缺漏。
- 修復元件升級後的相依性警告與未使用的匯入。

### 重大變更
- **架構分層與命名空間變更**：重構 `src/ui/` 與 `src/core/mods/` 命名空間，移除舊版 `mod_provider_resolver.py`、`http_utils.py` 與 `mod_management/review.py`，相關呼叫端需適配新的 Session 與 WorkScope 介面。
- **UI 框架底層全面替換**：移除所有舊有 Tkinter 風格適配器與相容層，完全以 PySide6 與 QFluentWidgets 原生 API 開發。

## v1.7.2 - 2026-06-05

### 新增
- **UI 視覺升級 (Fluent Design)**：導入 `PySide6-Fluent-Widgets` 框架擴充，新增 `fluent.py` 封裝 Fluent 風格元件，全面翻新主視窗與子選單（如伺服器建立、模組管理、伺服器設定）的視覺語彙與互動體驗。

### 調整
- **更新與封裝機制最佳化**：全面優先改用「系統安裝程式」進行發佈，正式移除可攜式模式（Portable mode）及打包腳本 (`package-portable.ps1`) 支援，簡化後續的自動更新選擇流程。
- **核心架構重構**：重構 `server_manager.py`、`server_instance.py` 等核心類別體系，並將耗時任務（如雜湊計算、線上資源驗證）進一步整合至共用的並行工作池（Worker Pool），降低資源佔用。
- **設定與 I/O 強化**：調整 `settings_manager.py` 與 `subprocess_utils.py`，最佳化子處理程序生命週期管理，並套用更安全的序列化保護與重新啟動機制。
- **政策與手冊更新**：更新官方資安通報政策與漏洞處理時程；並於《使用者手冊》與相關文檔中補充了 Quilt 與 NeoForge 的完整支援細節。

### 修正
- 修正 `update_parsing.py` 在遠端資源檢查與版本驗證時的錯誤攔截邏輯，避免網路異常導致主程式崩潰。
- 新增與修正大量自動化測試覆蓋：包含更新檢查器互動模擬 (`test_update_checker_installer_smoke.py`)、UI 元件排版測試、模組清單整合測試等。

## v1.7.1 - 2026-05-06

### 新增
- **新增載入器支援**：全面支援 Quilt (1.14+) 及 NeoForge (1.20.1+) 模組載入器，包含下載、快取、伺服器偵測與相容性過濾功能。
- **UI 底層重構**：導入原生 PySide6 封裝（`qt_widgets`、`qt_runtime`）及生命週期管理機制，提升畫面渲染與內部執行緒排程穩定性。
- **擴充自動化測試**：增加針對 HTTP 下載、Qt UI 版面配置 (`test_qt_widget_layout_smoke.py`)、主監控畫面 (`test_server_monitor_window_players.py`) 等層級的最新測試模組。

### 調整
- **UI 框架遷移**：全面將所有視窗結構與管理工具 (`main_window`, `manage_server_frame`, `mod_management` 等) 移植至 Qt 環境，並刪除與舊版 CustomTkinter 綁定的遺留檔案（例如 `virtual_list.py`）。
- **網路核心優化**：移除了 `async_http_utils.py`，統一下載行為至 `http_utils.py` 並支援 40 字元的 SHA-1 雜湊校驗（適用於 Maven 來源下載）。
- **I/O 與工具層簡化**：移除過多的工具拆分模組（如 `checksum_utils.py`、`json_io.py` 及 `safe_path_ops.py`），將邏輯直接整併進路徑檢查與儲存機制內。

### 修正
- 修正 Quilt 與 NeoForge 線上模組過濾問題：移除原先的相容別名擴展邏輯（alias logic），改採單一核心及原生 API 解析。
- 修正不同執行緒存取 UI 時可能造成的崩潰問題（透過 Qt `invoke_later` 與工作排程等統一控管）。
- 修正主題切換行為：主題預設改為「依照系統設定」，並在每次啟動及系統深淺色變更時自動同步套用 UI 主題。
- 修正 Java 版本支援政策 (`server_runtime_utils_jvm_policy`) 計算基準，以強化啟動環境相容判斷。

### 重大變更
- **UI 底層更迭**：原有的視窗控制介接完全被 PySide6 邏輯取代，捨棄舊版 Tk 圖形系統。
- **載入器關聯定義**：不再允許 Modrinth 跨平台相容替用判定，所有模組相容定義嚴格追隨各別的 loader 原生要求。

## v1.7.0 - 2026-04-03

### 新增
- **線上模組搜尋系統**：新增 `mod_search_service`，支援線上模組搜尋、版本查詢與下載流程，並整合依賴解析與相容性檢查機制。
- **模組索引管線**：新增 `mod_index_manager`、`mod_provider_metadata` 與 `mod_semantics`，支援增量掃描與 provider 資料整併功能。
- **伺服器實例工具組**：新增 `server_instance` 及拆分後的 `server_detection_utils`、`server_detection_version_utils`、`server_properties_utils` 與 `server_runtime_utils` 以落實職責分離。
- **通用基礎設施**：新增 `background_task`（背景任務）、`atomic_writer`（原子寫入）、`exception_utils`（例外處理）、`update_parsing` 與 `virtual_list`（虛擬列表）等工具模組。
- **自動化測試**：新增並擴充 Smoke 與整合測試，涵蓋模組管理、版本解析、設定檔 I/O 及 UI DPI 適應行為。

### 調整
- **架構重構**：重構 `mod_management`、`manage_server_frame` 與 `main_window` UI 架構，降低模組間耦合度並改善操作流暢度。
- **效能優化**：優化 Java 與 I/O 熱路徑，導入快取機制與受限工作池（Task Pooling）並行處理，大幅降低重複掃描與雜湊運算成本。
- **建置流程優化**：調整 Nuitka 建置快取策略，修正環境變數處理邏輯，並更新可攜版封裝腳本。
- **CI/CD 與安全加固**：升級 GitHub Actions 工作流，整合 Bandit/detect-secrets 安全掃描與品質檢查機制。

### 修正
- 修正 Windows API 呼叫的相容性問題（導入保護性呼叫機制）。
- 修正多處 I/O 下載與解析流程中的銜接問題，提升系統啟動與模組操作的穩定性。
- 修正工作流程腳本中重複的設定值，降低 CI 自動化建置失敗的機率。

### 重大變更
- **模組管理架構更迭**：引入模組索引與 Metadata 提供者機制，既有的外部 Provider 或 UI 插件可能需要更新資料格式以維持相容。

## v1.6.6 - 2026-02-20

### 新增
- 無

### 調整
- `HTTPUtils` 新增 URL 驗證、每執行緒 Session 重用，並強化下載時的目錄建立與原子替換流程。
- `PathUtils` 強化 ZIP 解壓縮安全流程，並將 JSON 寫入改為 `os.replace` 原子更新。
- `SystemUtils` 重構程序快照與記憶體查詢流程，降低重複呼叫與資源洩漏風險。
- 關於視窗連結文字改用主題色 token，並統一對話框 icon 綁定行為。

### 修正
- 修正建立伺服器時最小記憶體欄位為空仍顯示整數警告的問題。
- 修正 `server.properties` 連接埠範圍上限，避免使用保留埠 `65535`。
- 修正首次切換 servers 目錄時可能缺少 `servers_config.json` 的初始化問題。
- 修正 `SystemUtils` 在非 Windows 或 API 呼叫失敗時的相容性問題。
- 修正 `HTTPUtils` 在批次請求中跨執行緒共用 `Session` 可能造成競態的問題。

### 重大變更
- 無

## v1.6.5 - 2026-02-07

### 新增
- 無

### 調整
- 改善 IO 操作流程，降低等待與阻塞。
- 強化模組與 JAR 檔案偵測機制。
- 提升訊息顯示與警告提示的一致性。
- 重構伺服器管理的記憶體設定介面，明確 Java 最小記憶體需求。
- 調整伺服器建立與主視窗導覽介面，簡化對話框與按鈕操作。
- 改善進度顯示效能，提升整體使用體驗。
- 統一 UI token 呼叫，取代硬編碼。
- 整合模組狀態相關程式碼，降低維護成本。

### 修正
- 修正並行處理項目過多導致卡頓的問題。
- 修正備份伺服器流程的異常行為。
- 修正檔案寫入流程的潛在問題。
- 修正部分安全性風險與錯誤處理缺漏。

### 重大變更
- 無

## v1.6.4 - 2026-02-06

### 新增
- `PathUtils` 新增 `is_path_within()`，用於驗證路徑是否位於指定目錄內，防止路徑穿越攻擊。
- `ServerPropertiesValidator` 新增 server.properties 屬性驗證器，支援型別檢查與範圍驗證。

### 調整
- `UpdateChecker` 重新設計 SHA256 驗證流程（下載前檢查、下載後驗證、路徑安全驗證、暫存清理）。
- `SubprocessUtils` 統一使用 `stdin=DEVNULL`，避免子程序等待輸入。
- 安裝程式啟動前新增使用者確認對話框。
- `server.properties` 讀寫流程強化，支援跳脫字元與特殊字元值。
- `HTTPUtils` 下載改為暫存檔完成後再原子替換。
- `MemoryUtils` 新增 `compact` 參數，支援簡潔/詳細記憶體格式。
- 全專案移除冗餘英文註解/docstring，統一簡潔文件風格，改善例外處理與條件結構。

### 修正
- 修正 `get_json_batch()` 傳入空列表時的處理。
- 改善錯誤日誌輸出，所有 `show_error()` 都同步寫入日誌。

### 重大變更
- 無

## v1.6.3 - 2026-02-04

### 新增
- 新增 `system_utils.py` 系統工具模組，提供記憶體監控與程序管理。

### 調整
- `PathUtils` 新增 Zip Slip 防護、檔案雜湊值計算與安全檔案操作。
- `SubprocessUtils` 強制 `shell=False`，降低命令注入風險。
- `UpdateChecker` 會自動刪除損壞下載檔案。
- `RuntimePaths`、`SubprocessUtils`、`UpdateChecker` 重構為類別。
- 新增 `call_on_ui()`、`run_async()`、`reveal_in_explorer()`，並改善視窗狀態管理。

### 修正
- 無

### 重大變更
- 移除 `psutil` 與 `types-psutil` 依賴。

## v1.6.2 - 2026-01-31

### 新增
- 完整可攜式模式支援（`.portable` 判定、`.config/.log` 相對路徑、可攜式自動更新與 checksum 驗證）。
- 新增 mypy/ruff 與 `scripts/format_lint_check.bat`。
- 新增 VSCode 開發環境設定。
- 新增 GitHub Actions 自動化建置與 Release 發布流程（含 SHA256）。

### 調整
- 程式碼與型別提示現代化，統一匯入順序與例外處理風格。
- 載入器管理流程重構，強化版本偵測、快取策略與穩定版過濾。
- 路徑管理與日誌管理重構，依可攜/安裝模式自動切換。
- 優化圖示大小、Nuitka 打包設定、建置腳本與文件內容。

### 修正
- 修正可攜版安裝時不應修改系統設定的問題。
- 修正批次檔中的 CMD 解析錯誤。
- 修正版本資訊讀取相容性問題。
- 修復 `package-portable.bat` 的變數展開問題。

### 重大變更
- 移除 `CODE_REVIEW_AND_COMPLIANCE.md`、`PLAGIARISM_DETECTION_TOOLS.md` 等冗餘文件。
- 移除舊版 `build_nuitka.bat`，統一使用 `build_installer_nuitka.bat`。
