# Changelog

所有重要的變更都會記錄在此文件中。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

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
