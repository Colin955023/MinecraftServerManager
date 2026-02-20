#  Minecraft 伺服器管理器 - 技術概覽 (Technical Overview)

本文件詳細說明 **Minecraft 伺服器管理器** 的技術架構、設計模式與實作細節。本專案參考了 [PrismLauncher](https://github.com/PrismLauncher/PrismLauncher) 與 [MinecraftModChecker](https://github.com/MrPlayerYork/MinecraftModChecker) 的設計理念，並針對伺服器管理場景進行了最佳化。

##  系統架構

本專案採用模組化的三層式架構設計，確保程式碼的可維護性與擴充性。

### 1. 核心層 (Core Layer) - src/core/
負責處理所有的業務邏輯與資料操作，不依賴於任何 UI 元件。
- **ServerManager**: 伺服器生命週期管理（建立、啟動、停止、監控）。
- **MinecraftVersionManager**: 負責從 Mojang 與載入器官方 API 獲取版本資訊。
- **LoaderManager**: 處理 Fabric、Forge 等模組載入器的安裝與配置。
- **ModManager**: 負責模組檔案的掃描、啟用/停用狀態切換。
- **ServerDetectionUtils**: 實作既有伺服器的自動偵測邏輯。

### 2. 介面層 (UI Layer) - src/ui/
基於 CustomTkinter 構建的現代化圖形介面，負責與使用者互動並展示資料。
- **MinecraftServerManager**: 應用程式主視窗與導航邏輯。
- **CreateServerFrame**: 伺服器建立精靈，引導使用者完成配置。
- **ManageServerFrame**: 伺服器管理儀表板，提供啟動、停止與監控入口。
- **ModManagementFrame**: 模組管理介面，提供直觀的模組列表與操作功能。
- **ServerMonitorWindow**: 獨立的伺服器監控視窗，顯示即時日誌與資源使用率。
- **CustomDropdown**: 自定義的下拉選單元件，解決原生元件樣式限制。

### 3. 工具層 (Utils Layer) - src/utils/
提供跨模組共用的通用功能與輔助函式。
- **JavaUtils / JavaDownloader**: Java 環境的偵測、驗證與自動下載。
- **Logger (標準 logging)**: 統一的日誌記錄系統，提供 loguru 風格介面並自動輪替日誌檔案。
- **SettingsManager**: 應用程式設定的持久化儲存與讀取。
- **UIUtils**: 通用的 UI 輔助函式，如對話框顯示、字體管理等。

##  專案檔案結構

```text
MinecraftServerManger/
   .gitignore
   COPYING.md
   LICENSE
   pyproject.toml
   quick_test.py
   README.md
   uv.lock
   assets/
      icon.ico
      version_info.txt
   docs/
      TECHNICAL_OVERVIEW.md
      USER_GUIDE.md
   scripts/
      build_installer_nuitka.bat
      format_lint_check.bat
      package-portable.ps1
      installer.iss
   src/
      __init__.py
      main.py
      core/
         __init__.py
         loader_manager.py
         mod_manager.py
         server_manager.py
         version_manager.py
      models/
         __init__.py
         models.py
      ui/
         __init__.py
         create_server_frame.py
         custom_dropdown.py
         main_window.py
         manage_server_frame.py
         mod_management.py
         server_monitor_window.py
         server_properties_dialog.py
         window_preferences_dialog.py
      utils/
         __init__.py
         app_restart.py
         font_manager.py
         http_utils.py
         java_downloader.py
         java_utils.py
         logger.py
         path_utils.py
         runtime_paths.py
         server_utils.py
         settings_manager.py
         ui_utils.py
         update_checker.py
         window_manager.py
      version_info/
         __init__.py
         version_info.py
```

##  核心元件重點

- **ServerManager**（core/server_manager.py）：以 `servers_config.json` 在使用者指定的主資料夾中持久化伺服器清單，能掃描、重偵測既有伺服器，並自動建立啟動批次檔與 `server.properties`。啟動流程會尋找已存在的啟動腳本（run/start_server/start/server.bat），並透過佇列串流輸出供 UI 控制台即時顯示。
- **LoaderManager**（core/loader_manager.py）：預抓 Fabric 與 Forge 版本清單並以快取檔保存；下載流程會先檢查或安裝最合適的 Java，再執行對應載入器安裝器，並回報進度。
- **MinecraftVersionManager**（core/version_manager.py）：使用多執行緒抓取 Mojang 版本資訊並快取，只回傳具備可用 server JAR 的正式版，避免 UI 等待過久。
- **Logging 與快取路徑**：`utils/logger.py` 以標準 logging 提供 loguru 風格 API。路徑支援便攜模式與安裝模式：
  - **便攜模式**：日誌 `.log/`、快取 `.config/Cache/`（相對於可執行檔目錄）
  - **安裝模式**：日誌與快取位於 `%LOCALAPPDATA%\Programs\MinecraftServerManager\` 下（`log/`、`Cache/`）
- **UI 模組**：`ui/main_window.py` 掛載各 Frame；`manage_server_frame.py` 支援偵測既有伺服器、右鍵重新檢測、設定備份路徑與打開備份資料夾；`server_monitor_window.py` 提供資源監控與即時控制台。
- **Lazy Re-export**：core、ui、utils 皆採 lazy 匯出策略，透過 package `__init__.py` 延遲載入實際模組以降低啟動開銷並減少循環 import。

##  模組匯出策略（re-export）

為了讓 import 更一致、降低跨模組耦合，本專案在多個 package 使用「lazy re-export」：

- `src/core/__init__.py`：集中匯出核心管理器（例如 `ServerManager`, `LoaderManager`, `MinecraftVersionManager`, `ModManager`）。
- `src/utils/__init__.py`：集中匯出常用工具（例如 `UIUtils`, `logger.get_logger`, `HTTPUtils`, `font_manager`, `get_settings_manager` 等）。
- `src/ui/__init__.py`：集中匯出 UI 主要入口（例如 `MinecraftServerManager` 與各 Frame/對話框）。

匯出採用 lazy import，可降低啟動時載入成本並減少循環 import 的風險。

##  使用者資料與伺服器資料路徑

### 安裝版本
- 使用者設定檔固定存放於：`%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json`
- 日誌檔案存放於：`%LOCALAPPDATA%\Programs\MinecraftServerManager\log\`
  - 日誌檔案命名格式：`YYYY-MM-DD-HH-mm.log`
  - 自動清理機制：最多保留 10 個檔案，超過時自動刪除最舊的
- `user_settings.json` 會記錄「使用者選擇的伺服器主資料夾」(base dir)，實際伺服器資料會放在該資料夾內的 `servers` 子資料夾。

### 可攜式版本
- 使用者設定檔存放於：與程式同目錄下的 `.config/user_settings.json`
- 日誌檔案存放於：與程式同目錄下的 `.log/` 資料夾
- 所有資料均相對於程式位置，允許複製到 USB 隨身碟或多個位置並獨立運行

##  部署方式

### 開發模式
```bash
# 需要 Python 3.10+ 和 Git
git clone https://github.com/Colin955023/MinecraftServerManager.git
cd MinecraftServerManager
py -m pip install --user -U uv
uv sync
uv run python -m src.main
```

##  重新啟動與診斷

- `src/utils/app_restart.py`：提供重啟偵測與重啟功能。
   - 在打包（packaged）模式下會嘗試執行可執行檔；在腳本（script）模式下會先以 `python <path>/main.py` 啟動，若找不到 `main.py` 則 fallback 為 `python -m src.main` 的模組啟動方式。
   - 提供 `get_restart_diagnostics()` 回傳 (supported, details) 字串，用於在 UI 中顯示為何無法自動重啟（例如路徑不存在或檔案權限問題）。

### 可攜式版本
- **生成方式**：
   1. 執行 `scripts/build_installer_nuitka.bat` 生成 `dist/MinecraftServerManager/`
   2. 執行 `scripts/package-portable.bat` 建立可攜式 ZIP
- **分發方式**：壓縮為 `.zip`，用戶解壓即可直接執行
- **包含內容**：
   - `MinecraftServerManager.exe` - 主程式
   - 其他運行時依賴與資源
- **優點**：無需安裝、可攜帶在 USB 上、資料獨立儲存
- **檔案路徑**：GitHub Release 發布為 `MinecraftServerManager-v*.*.* -portable.zip`

- **可攜式自動更新與驗證**：更新檢查器會在偵測到可攜式模式時優先尋找命名包含 `-portable.zip` 的 Release asset 並嘗試下載套用；若 Release 同時提供 checksum 檔案或在釋出說明中包含檔案雜湊，程式會嘗試驗證下載內容的完整性，驗證失敗時會在 UI 顯示錯誤並停止套用更新。

### 安裝版本
- **生成方式**：執行 `scripts/build_installer_nuitka.bat` 生成可執行檔，再透過 Inno Setup 打包
- **安裝位置**：`%LOCALAPPDATA%\Programs\MinecraftServerManager\`
- **優點**：自動更新、系統整合（開始菜單快捷方式、檔案關聯等）
- **自動更新機制**：程式啟動時自動檢查 GitHub Release，若有新版本則提示用戶下載並執行新版本安裝程式
- **檔案路徑**：GitHub Release 發布為 `MinecraftServerManager-v*.*.* -installer.exe`

##  技術堆疊 (Tech Stack)

### 核心語言與框架
- **Python 3.10+**: 專案開發語言。
- **CustomTkinter**: 基於 Tkinter 的現代化 UI 擴充庫，提供深色模式與圓角設計。
- **Nuitka**: 將 Python 程式編譯為高效能的可執行檔與依賴資料夾（standalone/onedir）。

### 關鍵第三方函式庫
- **requests**: 高階 HTTP 客戶端，用於版本資訊查詢與檔案下載。
- **psutil**: 跨平台系統監控，用於獲取 CPU 與記憶體使用率。
- **toml**: 解析 TOML 設定檔 (如 Fabric/Forge 配置)。
- **defusedxml**: 安全解析 XML（Forge maven-metadata），避免常見 XML 漏洞。

##  安全性與合規性

- **開源合規**: 本專案嚴格遵守開源授權規範，所有第三方依賴均符合授權要求。
- **資料隱私**: 應用程式僅在本地運行，不會收集或上傳使用者的伺服器資料。
- **網路安全**: 所有網路請求均透過 HTTPS 進行，確保資料傳輸安全。

