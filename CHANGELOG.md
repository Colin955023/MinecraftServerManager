# Changelog

## v1.7.0 - 2026-04-03

### 新增
- 新增線上模組搜尋/版本查詢與下載流程，加入 `mod_search_service` 與模組頁面整合能力（含依賴解析與相容性檢查）。
- 新增模組索引與 metadata 管線：`mod_index_manager`、`mod_provider_metadata`、`mod_semantics`，支援增量掃描與 provider 資料整併。
- 新增伺服器實例模型與工具拆分：`server_instance`、`server_detection_utils`、`server_detection_version_utils`、`server_properties_utils`、`server_runtime_utils`。
- 新增通用基礎設施：`background_task`、`atomic_writer`、`exception_utils`、`update_parsing`、`virtual_list`。
- 新增與擴充 smoke/整合測試，涵蓋模組管理、provider 協調、版本解析、設定 I/O、子程序與 UI 池化/DPI 行為。

### 調整
- 重構模組管理與 UI 架構（`mod_management`、`manage_server_frame`、`main_window`），降低耦合並改善操作流暢度。
- 將舊有大型工具模組拆分為職責明確的伺服器檢測/屬性/執行模組，並統一版本偵測流程。
- 優化 Java 與 I/O 熱路徑：加入快取與受限工作池並行處理，降低重複掃描與雜湊成本。
- 優化建置與打包流程：調整 Nuitka 快取策略、修正環境變數處理、更新可攜版封裝腳本。
- 重構 CI/CD 與安全掃描：升級 GitHub Actions 工作流程、整合 Bandit/detect-secrets 與品質檢查入口。
- 更新文件與相依套件，對齊目前模組系統與建置流程。

### 修正
- 修正 Windows API 呼叫相容性問題（採保護性呼叫如 `getattr`）。
- 修正多處 I/O、下載、解析與流程銜接問題，提升建置、啟動與模組操作穩定性。
- 修正部分工作流程與腳本中的重複或不一致設定，降低 CI 失敗機率。

### 重大變更
- 模組管理架構改變：引入模組索引與 metadata 提供者，既有外部 provider 或 UI 插件可能需要更新設定或資料格式。

## v1.6.6 - 2026-02-20

### 新增
- 無

### 調整
- `HTTPUtils` 新增 URL 驗證、每執行緒 Session 重用，並強化下載時的目錄建立與原子替換流程。
- `PathUtils` 強化 ZIP 解壓安全流程，並將 JSON 寫入改為 `os.replace` 原子更新。
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
