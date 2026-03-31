# 技術手冊

## 1. 技術棧

| 類別 | 使用套件／工具 |
|------|----------------|
| 語言 | Python 3.10+ |
| GUI | CustomTkinter + Tkinter |
| 打包 | Nuitka（可執行檔）、Inno Setup（安裝精靈） |
| 網路 | requests（集中 timeout / retry policy） |
| 系統監控 | psutil |
| XML 解析 | defusedxml（防止 XXE 攻擊） |
| 測試 | pytest（smoke、integration） |
| 靜態檢查 | ruff、mypy |

---

## 2. 架構概覽

```
src/main.py
 └── ui/main_window.py        主視窗、頁面組裝、背景工作排程
	 ├── core/server_manager  伺服器生命週期（建立／啟動／停止／備份）
	 ├── core/mod_manager     模組掃描、安裝、更新規劃
	 ├── core/version_manager Minecraft 版本查詢
	 ├── core/loader_manager  Fabric／Forge／NeoForge 版本快取
	 └── ui/mod_search_service Modrinth API 整合（搜尋、相容性分析、依賴規劃）
```

---

## 3. 模組職責

### `src/core/`

| 檔案 | 職責 |
|------|------|
| `server_manager.py` | 伺服器 CRUD、啟動／停止、備份 |
| `mod_manager.py` | 本地模組掃描、安裝、更新執行 |
| `version_manager.py` | Minecraft 版本列表查詢 |
| `loader_manager.py` | Fabric／Forge／NeoForge 版本查詢與 TTL 快取 |

### `src/ui/`

| 檔案 | 職責 |
|------|------|
| `main_window.py` | 主視窗框架、頁面切換 |
| `create_server_frame.py` | 建立伺服器精靈 |
| `manage_server_frame.py` | 伺服器清單與操作面板 |
| `mod_management.py` | 模組管理頁面 |
| `mod_search_service.py` | Modrinth 搜尋、相容性分析、依賴規劃 |
| `server_monitor_window.py` | 即時監控視窗 |

### `src/utils/`

| 檔案 | 職責 |
|------|------|
| `settings_manager.py` | 設定讀寫（singleton） |
| `http_utils.py` | requests session，集中 timeout／retry |
| `window_manager.py` | DPI 感知、視窗定位、狀態持久化 |
| `logger.py` | 集中日誌初始化 |
| `java_utils.py` / `java_downloader.py` | Java 自動偵測與下載 |
| `path_utils.py` / `runtime_paths.py` | 路徑解析（安裝版 vs. 可攜版） |

---

## 4. 視窗生命週期

主視窗與大多數對話框採固定的顯示順序，避免初始化時出現閃爍：

1. `withdraw()` — 先隱藏
2. 建立並佈置元件
3. `geometry()` / `minsize()` 設定尺寸
4. `deiconify()` — 完成後再顯示

視窗偏好（位置、大小）由 `window_manager` 持久化至設定檔。可調整視窗不強制設定 `maxsize`；主視窗狀態僅在可見時追蹤。模組相關 Treeview 支援雙擊欄位標題自動調整欄寬。

---

## 5. 效能設計

- **減少啟動網路請求**：loader 版本快取採 TTL（預設 12 小時），快取有效期間略過預抓。
- **為何是 12 小時**：在「資料新鮮度」與「API 請求量」間折衷；Minecraft 伺服器管理情境通常是長時間運行、重啟頻率低，12 小時可避免每次啟動都重新查詢，同時仍能在每日維運節奏內更新版本資訊。
- **快取失效自動重抓**：快取缺失或過期時 preload guard 自動解除，無需重啟程式。
- **列表差異更新**：Treeview 只更新變動列，不整批重繪。
- **Lazy re-export**：`__init__.py` 採延遲匯出，降低啟動 import 成本。

## 6. Modrinth Loader 相容邏輯（Prism 風格）

搜尋、版本過濾、hash 批次更新與相容性分析均採用與 Prism Launcher 相同的 loader 擴展策略。

### Loader Alias 擴展（`_expand_target_loader_aliases`）

| 伺服器 Loader | 額外帶入的 filter | 說明 |
|---|---|---|
| Quilt | `fabric` | Modrinth 上絕大多數 Quilt 相容模組只有 `fabric` 標籤 |
| NeoForge 1.20.1 | `forge` | 該版本是 Forge 的直接 fork，binary 完全相容；1.20.2+ 不擴展 |

### Dependency Project ID Override（`MODRINTH_LOADER_DEPENDENCY_OVERRIDES`，僅 Fabric loader）

當 Fabric 環境的模組依賴 Quilt 專屬套件時，自動重定向：

| 原始 Project ID | 套件名稱 | 重定向目標 |
|---|---|---|
| `qvIfYCYJ` | Quilt API / QSL | `P7dR8mSH`（Fabric API） |
| `lwVhp9o5` | Quilt Standard Libraries | `Ha28R6CL`（Fabric Language Kotlin / FSL） |

NeoForge / Forge loader 不套用此重定向。

## 7. 資料與設定路徑

| 模式 | 路徑 |
|------|------|
| 安裝版 | `%LOCALAPPDATA%\Programs\MinecraftServerManager\` |
| 可攜版 | 執行檔同層 `.config\`、`.log\` |

設定由 `settings_manager`（singleton）讀寫並持久化。

## 8. 開發指令

```bash
# 安裝依賴
uv sync

# 啟動程式
uv run python -m src.main

# 快速 smoke test
uv run quick_test.py

# 完整格式／型別／測試門禁
scripts/format_lint_check.bat
```

## 9. 建議閱讀順序

想快速理解整體架構，建議依此順序閱讀：

1. `src/main.py` — 進入點，環境初始化
2. `src/ui/main_window.py` — 整體 UI 框架與頁面切換
3. `src/core/server_manager.py` — 伺服器核心邏輯
4. `src/core/mod_manager.py` — 模組服務
5. `src/ui/mod_search_service.py` — Modrinth 整合（最複雜的模組）
6. `src/utils/window_manager.py` — 視窗管理慣例
