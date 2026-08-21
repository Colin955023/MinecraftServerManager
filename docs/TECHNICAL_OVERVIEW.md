# 技術手冊

## 1. 技術棧

| 類別 | 使用套件／工具 |
|------|----------------|
| 語言 | Python 3.14 |
| GUI | PySide6 / Qt Widgets / PySide6-Fluent-Widgets |
| 打包 | Nuitka（可執行檔）、Inno Setup（安裝精靈） |
| 網路 | httpx[http2]（集中 timeout / retry policy） |
| 版本解析 | packaging |
| XML 解析 | defusedxml（防止 XXE 攻擊） |
| JSON 處理 | orjson（高效能序列化與反序列化） |
| 測試 | pytest（smoke、integration） |
| 靜態檢查 | ruff、mypy、bandit、pylint、import-linter、detect-secrets |

---

## 2. 架構概覽

```
src/main.py
 └── ui/core_frames/main_window.py 主視窗、頁面組裝、背景工作排程
     ├── core/loader_manager.py   載入器核心管理與快取 (Vanilla/Fabric/Forge/Quilt/NeoForge)
     ├── core/server/             伺服器生命週期
     │   ├── server_crud.py       伺服器 CRUD 與設定檔管理
     │   ├── server_creation.py   交易式伺服器建立流程
     │   ├── server_import.py     交易式匯入、批次探索與重新偵測
     │   ├── server_startup.py    啟動／停止控制
     │   ├── server_backup.py     備份還原管理
     │   └── server_instance.py   伺服器實例狀態與行程管理
     ├── core/mods/               模組協調與 Modrinth 搜尋服務層
     │   ├── mod_manager.py       模組 orchestration（委派掃描／安裝／provider 辨識）
     │   ├── local_mod_scanner.py 本地模組掃描、JAR metadata 解析與快取回填
     │   ├── mod_file_installer.py 模組下載、安裝、替換、回滾與刪除
     │   ├── mod_provider_resolver.py provider metadata 與 Modrinth 身分解析
     │   ├── modrinth_service.py  Modrinth API 搜尋與查詢服務
     │   ├── compatibility_analyzer.py Modrinth 模組相容性分析
     │   ├── dependency_planner_facade.py 模組依賴規劃門面
     │   ├── revalidation_service.py 模組批次重新驗證服務
     │   └── mod_search_constants.py 模組搜尋與相容性常數定義
     ├── ui/core_frames/*         建立、管理、關於與設定主要框架
     ├── ui/dialogs/*             確認、JVM、屬性、還原、進度等對話框
     ├── ui/mods/*                本地模組列表、Review、安裝清單與樹狀同步顯示
     ├── ui/services/*            伺服器掃描計算與背景任務協調服務
     ├── ui/windows/*             即時伺服器監控視窗
     └── utils/*                  日誌、網路、Java支援、UI主題、執行期工具等
```

> 上圖為典型呼叫關係示意，非嚴格依賴方向規則。`models/` 為 core 與 ui 共用的資料結構層，未在上圖逐一標出所有引用點；完整的分層依賴方向與匯入邊界規則見第 3 節。

---

## 3. 模組邊界與依賴方向

為避免跨層誤用（例如 UI 直接繞過 core 存取底層工具、或子模組彼此耦合），專案採單向分層依賴，並以工具強制檢查，不僅靠文件約束。

### 分層方向

```
ui → core → models → utils
```

左方可依賴右方，右方不可反向匯入左方。此規則以 `import-linter` 定義於 `pyproject.toml` 的 `[tool.importlinter]`，執行 `uv run lint-imports` 檢查。

### 匯入邊界規則

- 跨資料夾一律經由該資料夾 `__init__.py` 的匯出匯入，禁止深入子模組（例如禁止 `from src.core.mods.mod_manager import X`，應寫 `from src.core import X`）。
- `__init__.py` 只允許出現在 `src/` 與 `src/<子資料夾>/`；二層子資料夾（如 `src/ui/mods/`、`src/core/mods/`）禁止建立 `__init__.py`。
- 每個 `__init__.py` 只匯出自己資料夾內的內容；`src/ui/__init__.py` 例外，可跨子資料夾匯出同一頂層套件內的模組。

以上規則由 `scripts/check_import_boundaries.py`（AST 掃描）自動檢查，與 `lint-imports` 一併整合進 `scripts/format_lint_check.bat`，作為強制關卡而非人工稽核。

---

## 4. 模組簡介

### `src/models/`

| 檔案 | 簡介 |
|------|------|
| `models.py` | 核心資料結構：`ServerConfig`、`ModrinthVersionLookupResult`、`LoaderVersion`、`OnlineModVersion`、`ResolvedDependencyReference` |

### `src/core/`

| 檔案 / 資料夾 | 簡介 |
|------|------|
| `loader_manager.py` | 載入器核心管理（支援 Vanilla, Fabric, Forge, Quilt, NeoForge 之版本快取與下載） |
| `server/server_crud.py` | 伺服器 CRUD 與設定檔管理 |
| `server/server_creation.py` | 以 staging、原子設定寫入與補償建立伺服器實例 |
| `server/server_import.py` | 以唯讀候選、受管複本與逐項結果統一匯入、批次探索及重新偵測 |
| `server/server_startup.py` | 伺服器啟動／停止控制 |
| `server/server_backup.py` | 伺服器備份與還原管理 |
| `server/server_instance.py` | 伺服器實例狀態與行程管理 |
| `mods/mod_manager.py` | 模組 orchestration，整合掃描／安裝／provider 辨識 |
| `mods/local_mod_scanner.py` | 本地模組掃描、JAR metadata 解析與快取回填 |
| `mods/mod_file_installer.py` | 模組下載、安裝、替換、回滾與刪除 |
| `mods/mod_provider_resolver.py` | provider metadata、slug / project id 正規化與搜尋 fallback |
| `mods/modrinth_service.py` | Modrinth API 搜尋與查詢服務 |
| `mods/compatibility_analyzer.py` | Modrinth 模組相容性分析 |
| `mods/dependency_planner_facade.py` | 模組依賴規劃門面與相依解析 |
| `mods/revalidation_service.py` | 模組批次重新驗證服務 |
| `mods/mod_search_constants.py` | 模組搜尋與相容性常數定義 |

### `src/ui/`

| 子目錄 / 檔案 | 簡介 |
|------|------|
| `core_frames/main_window.py` | 主視窗框架、頁面切換、延遲排程 |
| `core_frames/create_server_frame.py` | 建立伺服器精靈 |
| `core_frames/manage_server_frame.py` | 伺服器清單與操作面板 |
| `core_frames/about_preferences_frame.py` | 關於與視窗偏好設定整合頁面 |
| `core_frames/page_router.py` | 頁面路由與導航控制 |
| `dialogs/progress_dialog.py` | 進度對話框 |
| `dialogs/server_properties_dialog.py` | 伺服器屬性對話框 |
| `dialogs/jvm_args_dialog.py` | JVM 參數自訂與優化建議對話框 |
| `dialogs/server_creation_confirm_dialog.py` | 建立前參數與指令核對對話框 |
| `dialogs/restore_backup_dialog.py` | 備份還原對話框 |
| `dialogs/modal_msfluent_window.py` | 彈出視窗基底類別 |
| `mods/` | 模組管理主介面、Presenter、Review 視窗、樹狀列表同步與安裝執行器 |
| `services/manage_server_service.py` | 伺服器本機偵測與狀態計算服務 |
| `services/task_coordinator.py` | 跨頁面背景任務協調服務 |
| `windows/server_monitor_window.py` | 即時監控視窗 |

### `src/utils/`

| 子目錄 | 簡介 |
|--------|------|
| `core_utils/` | `logger`、`path_utils`、`atomic_writer`、`exception_utils`、`hash_utils` |
| `network_utils/` | `http_client` (集中 timeout/retry)、`request_retry_utils` |
| `java_support/` | Java 自動偵測、winget 安裝支援 |
| `ui_support/` | Fluent theme、window manager、DPI handling、dialog_utils、font_manager、icon_utils、qt_runtime、qt_widgets、task_utils、tree_utils、ui_config、ui_tokens、ui_utils、custom_dropdown |
| `runtime_utils/` | 延遲匯出、版本資訊、環境檢查、OS 判斷、Python 版本檢查、app_info、background_task、runtime_paths、settings_manager、singleton、subprocess_utils、system_utils、version_info |
| `mod_utils/` | 依賴規劃序列化、下載來源策略、本地模組 metadata 工具、Modrinth 查詢工具、Modrinth 版本查詢、模組依賴規劃、模組依賴參考工具、模組索引管理、模組 provider metadata、模組重新驗證批次工具、模組語意、模組版本過濾 |
| `server_utils/` | 伺服器常數、伺服器偵測工具、伺服器偵測版本工具、伺服器記憶體工具、伺服器屬性工具、伺服器執行期工具 |
| `update_utils/` | 更新檢查、更新解析、更新檢查適配器 |



---

## 5. 視窗生命週期

主視窗與大多數對話框採 Qt 視窗生命週期，避免在元件尚未完成佈局時顯示：

1. 建立 Qt widget 與 layout。
2. 透過 `WindowManager` 計算螢幕、尺寸與置中位置。
3. 呼叫 `resize()`、`move()`、`setMinimumSize()` 套用視窗幾何。
4. 元件完成後再呼叫 `show()`；需要最大化時延後呼叫 `showMaximized()`。

視窗偏好（位置、大小與最大化狀態）由 `ui_support/window_manager.py` 持久化至設定檔。可調整視窗不強制設定最大尺寸；主視窗狀態僅在視窗有效且非最小化時追蹤。模組相關 `qt.Treeview` 支援雙擊欄位標題自動調整欄寬。

高解析度顯示縮放交由 Qt 6 與 Windows 原生設定處理。Qt Widgets 使用 device-independent pixels，Qt 6 在 Windows 會自動套用使用者的顯示比例，因此專案內不再保存或套用額外的 UI 縮放倍率。

---

## 6. 效能設計

- **減少啟動網路請求**：loader 版本快取採 TTL（預設 12 小時），快取有效期間略過預抓。
- **為何是 12 小時**：在「資料新鮮度」與「API 請求量」間折衷；Minecraft 伺服器管理情境通常是長時間運行、重啟頻率低，12 小時可避免每次啟動都重新查詢，同時仍能在每日維運節奏內更新版本資訊。
- **快取失效自動重抓**：快取缺失或過期時 preload guard 自動解除，無需重啟程式。
- **列表差異更新**：Treeview 只更新變動列，不整批重繪。
- **Lazy re-export**：`__init__.py` 採延遲匯出，降低啟動 import 成本。
- **JVM 參數最佳化**：建立伺服器時動態依據所選記憶體大小、Minecraft 建議 Java 版本以及載入器類型，預載最適合的 JVM 參數（Java 21+ 使用 ZGC；舊版使用 G1GC Aikar's flags），確保出廠即具備優秀效能。

## 7. 支援的伺服器類型與載入器

本專案支援原版伺服器與四種模組載入器：

| 載入器 | 支援版本 | 說明 |
|---|---|---|
| Vanilla（原版） | 所有版本 | 官方 Minecraft 伺服器，無模組載入器 |
| Fabric | 1.14+ | 輕量級模組載入器，廣泛支援 1.16+ 版本 |
| Quilt | 1.14+ | 與 Fabric 生態相近的模組載入器，使用 Quilt Meta API 查詢版本 |
| Forge | 1.5+ | 老牌模組載入器；可用版本以 Maven metadata 可解析結果為準 |
| NeoForge | 1.20.1+ | Forge 生態的現代分支；可用版本以 NeoForge Maven metadata 為準 |

### 版本管理

- **Fabric / Quilt**：從官方 Fabric / Quilt Meta API 取得穩定版本清單，支援依 Minecraft 版本過濾
- **Forge / NeoForge**：從 Maven metadata 解析版本，每個 Minecraft 版本保留最新 10 個版本

## 8. 資料與設定路徑

- **設定**：`%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json`
- **日誌**：`%LOCALAPPDATA%\Programs\MinecraftServerManager\log\`
- **快取**：`%LOCALAPPDATA%\Programs\MinecraftServerManager\Cache\`

設定由 `runtime_utils/settings_manager.py` 統一讀寫並持久化，對外主要透過 `get_settings_manager()` 提供共享實例。

## 9. 開發指令

```bash
# 安裝依賴
uv sync

# 啟動程式
uv run python -m src.main

# 匯入邊界檢查（分層方向 + 深層匯入 + __init__.py 規則）
uv run lint-imports
uv run scripts/check_import_boundaries.py

# 測試（先同步測試套件）
uv sync --group test
uv run pytest -q

# 完整格式／型別／測試門禁（已包含上述所有檢查）
scripts/format_lint_check.bat

# 產生綜合報告
uv run report\comprehensive_report.py
```

## 10. 建議閱讀順序

想快速理解整體架構，建議依此順序閱讀：

1. `src/main.py` — 進入點，環境初始化
2. `src/models/models.py` — 核心資料結構，貫穿全專案
3. `src/ui/core_frames/main_window.py` — 整體 UI 框架與頁面切換
4. `src/core/server/` — 伺服器核心邏輯
5. `src/core/loader_manager.py` — 載入器核心管理
6. `src/core/mods/` — 模組協調與 Modrinth 線上搜尋／依賴規劃服務
7. `src/ui/mods/` — 模組管理介面、Presenter 與 Review 視窗
8. `src/utils/ui_support/window_manager.py` — 視窗管理慣例
