# 技術手冊

## 1. 技術棧

| 類別 | 使用套件／工具 |
|------|----------------|
| 語言 | Python 3.14 |
| GUI | PySide6 / Qt Widgets |
| 打包 | Nuitka（可執行檔）、Inno Setup（安裝精靈） |
| 網路 | requests + urllib3 Retry（集中 timeout / retry policy） |
| 版本解析 | packaging |
| XML 解析 | defusedxml（防止 XXE 攻擊） |
| Release Notes 解析 | markdown |
| 測試 | pytest（smoke、integration） |
| 靜態檢查 | ruff、mypy、bandit |

---

## 2. 架構概覽

```
src/main.py
 └── ui/main_window.py            主視窗、頁面組裝、背景工作排程
     ├── core/server_manager.py   伺服器生命週期（建立／啟動／停止／備份）
     ├── core/mod_manager.py      模組協調層（委派掃描／安裝／provider 辨識）
     ├── core/local_mod_scanner.py 本地模組掃描、JAR metadata 解析
     ├── core/mod_file_installer.py 模組檔案安裝、替換、回滾與刪改
     ├── core/mod_provider_resolver.py provider metadata 與 Modrinth 身分解析
     ├── core/version_manager.py  Minecraft 版本查詢
     ├── core/loader_manager.py   Fabric／Forge／Quilt／NeoForge 版本查詢與快取
     ├── ui/mod_management/*      本地模組列表、Review、安裝清單與同步顯示
     ├── ui/mod_search_service/*  Modrinth 搜尋、相容性分析、依賴規劃
     └── utils/update_checker.py  更新檢查、下載與套用流程
```

---

## 3. 模組職責

### `src/core/`

| 檔案 | 職責 |
|------|------|
| `server_manager.py` | 伺服器 CRUD、啟動／停止、備份 |
| `mod_manager.py` | 模組 orchestration，整合掃描／安裝／provider 辨識 |
| `local_mod_scanner.py` | 本地模組掃描、JAR metadata 解析與快取回填 |
| `mod_file_installer.py` | 模組下載、原子替換、回滾、匯入、刪除、啟停 |
| `mod_provider_resolver.py` | provider metadata、slug / project id 正規化與搜尋 fallback |
| `version_manager.py` | Minecraft 版本列表查詢 |
| `loader_manager.py` | Fabric／Forge 版本查詢與 TTL 快取 |

### `src/ui/`

| 檔案 | 職責 |
|------|------|
| `main_window.py` | 主視窗框架、頁面切換 |
| `create_server_frame.py` | 建立伺服器精靈 |
| `manage_server_frame.py` | 伺服器清單與操作面板 |
| `mod_management/` | 模組管理頁面、Review、樹狀列表同步與安裝執行 |
| `mod_search_service/` | Modrinth 搜尋、相容性分析、依賴規劃與 provider 轉接 |
| `server_monitor_window.py` | 即時監控視窗 |

### `src/utils/`

| 檔案 | 職責 |
|------|------|
| `settings_manager.py` | 設定讀寫與共享設定管理器存取 |
| `http_utils.py` | requests session，集中 timeout／retry |
| `window_manager.py` | Qt 視窗定位與狀態持久化 |
| `logger.py` | 集中日誌初始化 |
| `java_utils.py` / `java_downloader.py` | Java 自動偵測；必要時在背景透過 winget 安裝官方 JDK / JRE 並自動同意授權 |
| `path_utils.py` / `runtime_paths.py` | 路徑解析（安裝版 vs. 可攜版） |
| `update_checker.py` / `update_parsing.py` | GitHub Releases 更新檢查、資產選擇與驗證 |

---

## 4. 視窗生命週期

主視窗與大多數對話框採固定的顯示順序，避免初始化時出現閃爍：

1. `withdraw()` — 先隱藏
2. 建立並佈置元件
3. `geometry()` / `minsize()` 設定尺寸
4. `deiconify()` — 完成後再顯示

視窗偏好（位置、大小）由 `window_manager` 持久化至設定檔。可調整視窗不強制設定 `maxsize`；主視窗狀態僅在可見時追蹤。模組相關 Treeview 支援雙擊欄位標題自動調整欄寬。

高解析度顯示縮放交由 Qt 6 與 Windows 原生設定處理。Qt Widgets 使用 device-independent pixels，Qt 6 在 Windows 會自動套用使用者的顯示比例，因此專案內不再保存或套用額外的 UI 縮放倍率。

---

## 5. 效能設計

- **減少啟動網路請求**：loader 版本快取採 TTL（預設 12 小時），快取有效期間略過預抓。
- **為何是 12 小時**：在「資料新鮮度」與「API 請求量」間折衷；Minecraft 伺服器管理情境通常是長時間運行、重啟頻率低，12 小時可避免每次啟動都重新查詢，同時仍能在每日維運節奏內更新版本資訊。
- **快取失效自動重抓**：快取缺失或過期時 preload guard 自動解除，無需重啟程式。
- **列表差異更新**：Treeview 只更新變動列，不整批重繪。
- **Lazy re-export**：`__init__.py` 採延遲匯出，降低啟動 import 成本。

## 6. 支援的模組載入器

本專案支援以下四種模組載入器：

| 載入器 | 支援版本 | 說明 |
|---|---|---|
| Vanilla（原版） | 所有版本 | 官方 Minecraft 伺服器，無模組載入器 |
| Fabric | 1.14+ | 輕量級模組載入器，廣泛支援 1.16+ 版本 |
| Quilt | 1.14+ | 基於 Fabric 的改進版本，提供更好的相容性 |
| Forge | 1.5+ | 功能豐富的老牌模組載入器，支援 1.5 到最新版本 |
| NeoForge | 1.20.1+ | Forge 的現代化分支，在 1.20.1+ 上支援 |

### 版本管理

- **Fabric / Quilt**：從官方 Fabric / Quilt Meta API 取得穩定版本清單，支援依 Minecraft 版本過濾
- **Forge / NeoForge**：從 Maven metadata 解析穩定版本，每個 Minecraft 版本保留最新 10 個版本

## 7. 資料與設定路徑

| 模式 | 設定 | 日誌 | 快取 |
|------|------|------|------|
| 安裝版 | `%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json` | `%LOCALAPPDATA%\Programs\MinecraftServerManager\log\` | `%LOCALAPPDATA%\Programs\MinecraftServerManager\Cache\` |
| 可攜版 | `<exe_dir>\.config\user_settings.json` | `<exe_dir>\.log\` | `<exe_dir>\.config\Cache\` |

設定由 `settings_manager` 模組統一讀寫並持久化，對外主要透過 `get_settings_manager()` 提供共享實例。

## 8. 開發指令

```bash
# 安裝依賴
uv sync

# 啟動程式
uv run python -m src.main

# 快速 test
uv run quick_test.py

# 完整格式／型別／測試門禁
scripts/format_lint_check.bat

# 產生綜合報告
uv run report\comprehensive_report.py
```

## 9. 建議閱讀順序

想快速理解整體架構，建議依此順序閱讀：

1. `src/main.py` — 進入點，環境初始化
2. `src/ui/main_window.py` — 整體 UI 框架與頁面切換
3. `src/core/server_manager.py` — 伺服器核心邏輯
4. `src/core/mod_manager.py` — 模組服務
5. `src/ui/mod_search_service/` — Modrinth 整合（最複雜的模組）
6. `src/utils/window_manager.py` — 視窗管理慣例
