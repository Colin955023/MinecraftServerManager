# 技術手冊

## 技術棧

| 類別 | 工具 |
|---|---|
| 執行環境 | Python `>=3.14,<3.15`、Windows 10／11 |
| GUI | PySide6、PySide6-Fluent-Widgets |
| 網路／資料 | httpx、orjson、packaging、defusedxml |
| 系統／日誌 | psutil、loguru |
| 打包 | Nuitka onefile |
| 品質 | pytest、Ruff、Mypy、Pylint、Bandit、Vulture、import-linter、detect-secrets |

相依套件與最低版本以 `pyproject.toml`、鎖定版本以 `uv.lock` 為準。

## 架構

```text
src/main.py
└─ ui/core_frames/main_window.py        唯一 production composition root
   ├─ core/server/                      建立、匯入、檢查、執行、屬性、備份
   ├─ core/mods/                        掃描、安裝、Provider、Modrinth、規劃
   ├─ core/loader_manager.py            載入器版本與安裝器
   ├─ ui/core_frames|dialogs|mods|...   Qt／Fluent UI adapters
   ├─ models/models.py                  共享領域資料
   └─ utils/                            檔案、網路、Java、UI、執行期工具
```

依賴方向由 import-linter 強制：

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
uv run lint-imports
uv run scripts\check_import_boundaries.py
```

## 目錄職責

### `src/core/server/`

| 檔案 | 職責 |
|---|---|
| `server_crud.py` | 伺服器登錄與設定檔 |
| `server_creation.py` | 交易式建立與補償 |
| `server_import.py` | 資料夾／ZIP 匯入、探索、重新偵測 |
| `server_inspector.py` | 唯讀內容檢查 |
| `server_runtime.py` | 統一啟動與首次初始化生命週期；協調備份、還原、刪除期間的維護保留 |
| `server_properties.py` | `server.properties` 唯一真相來源 |
| `server_backup.py` | 原子 ZIP 備份、交易式快照還原與失敗回滾 |

### `src/core/mods/`

| 檔案 | 職責 |
|---|---|
| `mod_manager.py` | 掃描、安裝與 provider orchestration |
| `local_mod_scanner.py` | JAR metadata 與快取回填 |
| `mod_file_installer.py` | 下載、安裝、替換、回滾、刪除 |
| `provider_identity.py` | provider 身分與生命週期 |
| `modrinth_service.py` | Modrinth 查詢 |
| `dependency_planner_facade.py` | `ModPlanning` 唯一 use-case interface |
| `compatibility_analyzer.py` | 內部純相容性分析 |
| `mod_planning_ports.py` | provider／loader rules 窄 port |
| `modrinth_planning_adapter.py` | production adapters |

### `src/ui/`

- `core_frames/`：主視窗、建立、管理、偏好與導航。
- `dialogs/`：建立確認、屬性、JVM、還原及進度對話框。
- `mods/`：具名 feature、Session、Review workflow、install executor、tree projection。
- `services/`：管理頁狀態計算與跨頁工作協調。
- `windows/`：伺服器監控。

`ModManagementFrame` 只負責根組裝與生命週期，不代理 feature command。`review_*` implementation 除 `review_workflow.py`、`review_contracts.py` 外不是外部介面。

### `src/utils/`

- `core_utils/`：原子寫入、路徑、雜湊、例外、日誌、單位、版本。
- `network_utils/`：集中 HTTP timeout、retry、URL 驗證及一般回應內容上限。
- `java_support/`：Java 偵測與 winget 安裝。
- `ui_support/`：Fluent 主題、UI tokens、狀態、`UIUtils`、`UIWorkScope`。
- `runtime_utils/`：路徑、設定、背景工作、subprocess、系統狀態。
- `mod_utils/`：依賴序列化、下載政策、metadata、index、語意與版本過濾。
- `server_utils/`：記憶體、properties codec、啟動命令、版本語意。
- `update_utils/`：更新檢查與解析。

## 重要實作規則

- JSON／文字寫入使用原子寫入；不要直接覆寫正式檔。
- GUI 可見控制項使用 QFluentWidgets；PySide6 保留基礎設施，檔案選擇器集中於 `UIUtils`。
- UI 背景工作經 `UIWorkScope`；主視窗關閉時依序保存設定、shutdown runtime、停止計時器、drain 工作，再關閉其餘視窗。
- `server.properties` 不複製到 `ServerConfig`。
- production 與 tests 應驗證同一外部 seam；不得為測試新增 production API。

## 開發命令

```bat
uv sync
uv run python -m src.main

uv sync --group test
uv run pytest -q

scripts\format_lint_check.bat
uv run report\comprehensive_report.py
```

使用方式見 [USER_GUIDE.md](USER_GUIDE.md)。
