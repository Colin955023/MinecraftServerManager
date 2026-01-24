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
- **Logger (基於 loguru)**: 統一的日誌記錄系統，支援多級別日誌輸出與自動日誌管理。
- **SettingsManager**: 應用程式設定的持久化存儲與讀取。
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
      CODE_REVIEW_AND_COMPLIANCE.md
   scripts/                        # 依 .gitignore 忽略清單，結構表不列出被忽略的腳本
      build_installer_nuitka.bat
      build_nuitka.bat
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
         log_utils.py
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

##  模組匯出策略（re-export）

為了讓 import 更一致、降低跨模組耦合，本專案在多個 package 使用「lazy re-export」：

- `src/core/__init__.py`：集中匯出核心管理器（例如 `ServerManager`, `LoaderManager`, `MinecraftVersionManager`, `ModManager`）。
- `src/utils/__init__.py`：集中匯出常用工具（例如 `UIUtils`, `LogUtils`, `HTTPUtils`, `font_manager`, `get_settings_manager` 等）。
- `src/ui/__init__.py`：集中匯出 UI 主要入口（例如 `MinecraftServerManager` 與各 Frame/對話框）。

匯出採用 lazy import，可降低啟動時載入成本並減少循環 import 的風險。

##  使用者資料與伺服器資料路徑

- 使用者設定檔固定存放於：`%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json`
- 日誌檔案存放於：`%LOCALAPPDATA%\Programs\MinecraftServerManager\log\`
  - 日誌檔案命名格式：`YYYY-MM-DD-HH-mm.log`
  - 自動清理機制：當日誌資料夾超過 10MB 時，會自動刪除相當於 8MB 的舊日誌
- `user_settings.json` 會記錄「使用者選擇的伺服器主資料夾」(base dir)，實際伺服器資料會放在該資料夾內的 `servers` 子資料夾。

##  技術堆疊 (Tech Stack)

### 核心語言與框架
- **Python 3.9+**: 專案開發語言。
- **CustomTkinter**: 基於 Tkinter 的現代化 UI 擴充庫，提供深色模式與圓角設計。
- **Nuitka**: 將 Python 程式編譯為高效能的可執行檔與依賴資料夾（standalone/onedir）。

### 關鍵第三方函式庫
- **requests / aiohttp**: 處理 HTTP 請求，用於獲取版本資訊與下載檔案。
- **psutil**: 跨平台系統監控，用於獲取 CPU 與記憶體使用率。
- **lxml**: 高效能 XML 解析，用於處理 Maven Metadata。
- **toml**: 解析 TOML 設定檔 (如 Fabric/Forge 配置)。
- **loguru**: 現代化的日誌記錄函式庫，提供彩色輸出、自動日誌輪轉與執行緒安全等功能。

##  安全性與合規性

- **開源合規**: 本專案嚴格遵守開源授權規範，所有第三方依賴均符合授權要求。
- **資料隱私**: 應用程式僅在本地運行，不會收集或上傳使用者的伺服器資料。
- **網路安全**: 所有網路請求均透過 HTTPS 進行，確保資料傳輸安全。

詳細資訊請參閱 [程式碼規範與審查報告](CODE_REVIEW_AND_COMPLIANCE.md)。
