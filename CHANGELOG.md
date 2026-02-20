# Changelog

## v1.6.6 - 2026-02-20

### 修復
- 修正建立伺服器時最小記憶體欄位為空仍顯示整數警告的問題
- 修正 `server.properties` 連接埠範圍上限，避免使用保留埠 `65535`
- 修正首次切換 servers 目錄時可能缺少 `servers_config.json` 的初始化問題
- 修正 `SystemUtils` 在非 Windows 或 API 呼叫失敗時的相容性問題

### 優化
- `HTTPUtils` 新增 URL 驗證、重用 Session，並強化下載時的目錄建立與原子替換流程
- `PathUtils` 強化 ZIP 解壓安全流程，並將 JSON 寫入改為 `os.replace` 原子更新
- `SystemUtils` 重構進程快照與記憶體查詢流程，降低重複呼叫與資源洩漏風險

### 介面調整
- 關於視窗連結文字改用主題色 token，並統一對話框 icon 綁定行為

## v1.6.5 - 2026-02-07

### 修復
- 修正並行處理項目過多導致卡頓的問題
- 修正備份伺服器流程的異常行為
- 修正檔案寫入流程的潛在問題
- 修正部分安全性風險與錯誤處理缺漏

### 優化
- 改進 IO 操作流程，降低等待與阻塞
- 強化模組與 JAR 檔案偵測機制
- 提升訊息顯示與警告提示的一致性

### 介面調整
- 重構伺服器管理的記憶體設定介面，明確 Java 最小記憶體需求
- 調整伺服器建立與主視窗導覽介面，簡化對話框與按鈕操作
- 改善進度顯示效能以提升整體使用體驗

### 開發者調整
- 統一 UI token 呼叫，取代硬編碼
- 整合模組狀態相關程式碼，降低維護成本

## v1.6.4 - 2026-02-06

### 新增
- **安全性**
  - `PathUtils`: 新增 `is_path_within()` 方法，用於驗證路徑是否在指定目錄內，防止路徑穿越攻擊
  - `ServerPropertiesValidator`: 新增 server.properties 屬性驗證器，支援型別檢查與範圍驗證

### 優化
- **安全性強化**
  - UpdateChecker: 重新設計 SHA256 驗證流程
    - 下載前先線上確認 SHA256 是否存在（拒絕下載無 SHA256 的檔案）
    - 下載後立即驗證 SHA256（驗證失敗立即刪除檔案）
    - 新增路徑安全性檢查（確保所有操作檔案都在合法目錄內）
    - 自動清理所有暫存檔案，避免殘留
  - SubprocessUtils: 所有子進程啟動統一使用 `stdin=DEVNULL`，避免進程等待輸入
  - 安裝程式啟動前新增使用者確認對話框

- **功能改進**
  - `server.properties` 處理重大改進
    - 支援 Java properties 格式的跳脫字元（`\:`, `\=`, `\n`, `\t` 等）
    - 改進讀取邏輯，正確處理包含 `=` 或 `:` 的屬性值
    - 改進寫入邏輯，自動處理特殊字元的跳脫
  - HTTPUtils: 下載檔案時使用臨時檔案，完成後再重命名，避免下載失敗時產生損壞檔案
  - MemoryUtils: 新增 `compact` 參數，支援簡潔/詳細兩種記憶體格式顯示

- **程式碼品質提升**
  - 全專案移除冗餘的英文註解與 docstring
  - 統一 docstring 為簡潔的單行格式
  - 改進異常處理機制（logger.py: 統一異常格式化邏輯）
  - 移除所有 `(Static Class)` 等多餘標註

### 修復
- 修正 `get_json_batch()` 在傳入空列表時的處理
- 改善錯誤日誌輸出，所有 `show_error()` 都同步寫入日誌

## v1.6.3 - 2026-02-04

### 新增
- 新增 `system_utils.py` 系統工具模組，使用 Windows API 取代 psutil 依賴
  - 提供記憶體監控與進程管理功能
  - 減少打包體積約 500KB

### 優化
- **安全性強化**
  - PathUtils: 新增 Zip Slip 防護、檔案雜湊值計算 (SHA256/MD5)、安全的檔案操作
  - SubprocessUtils: 強制 `shell=False` 防止命令注入攻擊
  - UpdateChecker: 自動刪除損壞的下載檔案

- **程式碼重構**
  - 將 `RuntimePaths`、`SubprocessUtils`、`UpdateChecker` 重構為類別
  - 統一模組引用方式，降低耦合度

- **UI 改進**
  - 新增 `call_on_ui()`、`run_async()`、`reveal_in_explorer()` 工具函數
  - 改善視窗狀態管理與錯誤處理

### 移除
- 移除 psutil 及 types-psutil 依賴

## v1.6.2 - 2026-01-31

### 新增

#### 便攜版完整支援
- 新增便攜模式自動檢測（使用 `.portable` 標記檔）
- 設定與日誌改為儲存於相對路徑（`.config/`、`.log/`）
- 支援 USB 隨身碟使用，資料完全獨立、不影響系統
- 支援便攜版自動更新與 SHA256 checksum 驗證
- 可攜版更新檢查 UI 重新啟用

#### 開發工具
- 新增 mypy 與 ruff 程式碼格式化與品質檢查工具
- 新增 `format_lint_check.bat` 腳本，方便開發時檢查程式碼品質
- 新增 VSCode 開發環境設定檔（`.vscode/`）

#### 自動化構建與發布
- GitHub Actions 自動化構建、生成 SHA256、發布 Release
- 自動從 GitHub Release 下載並驗證 checksum
- 支援便攜版 ZIP 和安裝檔的 SHA256 自動生成

### 優化

#### 程式碼品質提升
- 移除冗餘編碼宣告（Python 3 預設使用 UTF-8）
- 統一 docstring 為簡潔單行格式
- 規範所有模組的匯入順序與分組
- 現代化型別提示寫法（`Optional[T]` → `T | None`、`Dict/List` → `dict/list`）
- 統一異常處理方式，明確保留錯誤來源（使用 `from e`）
- 簡化條件判斷結構，移除冗餘 else/elif
- 全專案程式碼符合 PEP 8 風格規範

#### 載入器管理優化
- 整合並重構載入器偵測邏輯，降低維護成本
- 過濾 Fabric 與 Forge 快取中的測試版本（Beta、Alpha、RC），僅保留穩定版
- 改善版本偵測機制，改以官方 Mojang / Forge API 為主要依據
- 統一檔案 I/O 與 JAR 中繼資料解析流程
- 更新 Fabric Installer 至 1.1.1
- 移除多餘的包裝函式，精簡程式碼結構

#### 路徑管理重構
- 自動支援便攜模式與安裝模式切換
- 日誌系統依執行模式選擇合適儲存路徑
- 改善更新檢查器的錯誤處理和日誌記錄

#### 其他改進
- 壓縮應用程式圖示檔案大小（244KB → 59KB）
- 優化 Nuitka 打包設定，減少執行檔大小
- 更新建置腳本，簡化本地構建流程
- 更新 README 與使用者指南，補充便攜版說明

### 修復
- 修正可攜版安裝時不應修改系統設定的問題
- 修正批次檔案中的 CMD 解析錯誤
- 修正版本資訊讀取的相容性問題
- 修復 `package-portable.bat` 的變數展開問題

### 移除
- 移除冗餘文件（`CODE_REVIEW_AND_COMPLIANCE.md`、`PLAGIARISM_DETECTION_TOOLS.md`）
- 移除舊版 `build_nuitka.bat`，統一使用 `build_installer_nuitka.bat`
