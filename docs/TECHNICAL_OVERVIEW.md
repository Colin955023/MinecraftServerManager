# Minecraft 伺服器管理器技術手冊

本手冊說明 Minecraft 伺服器管理器程式所採用的技術堆疊、分層架構、核心演算法與安全機制。

## 技術棧總覽

| 領域 | 技術與組件 | 說明 |
|---|---|---|
| 核心平台 | .NET 10（`net10.0-windows`） | 採用最新 LTS 框架，提供高效能 JIT 與非同步 I/O |
| 使用者介面 | WPF（Windows Presentation Foundation） | 原生 Windows 桌面框架，落實 MVVM 模式與資料綁定 |
| 資料序列化 | `System.Text.Json` | 高效能唯讀 Span 與串流 JSON 序列化／反序列化 |
| 網路通訊 | `System.Net.Http.HttpClient` | 集中連線池管理、自動重試預算與完整超時控制 |
| 外部程序管理 | `System.Diagnostics.Process` | 異步串流重定向、優雅停止（Graceful Shutdown）與程序樹強制清理 |
| 正則編譯最佳化 | `[GeneratedRegex]` Source Generator | 編譯期產生比對狀態機，零執行期正則解析開銷 |
| 平行運算 | `Parallel.ForEachAsync` | 多核心平行化處理模組掃描與檔案雜湊運算 |
| 測試驗證 | xUnit、UnitTests、IntegrationTests | 完整本機隔離測試，無外部網路與使用者環境依賴 |
| 封裝發布 | 原生 Single-File、微軟官方安全壓縮 | 關閉未使用執行期功能開關（Feature Switches），無第三方加殼 |

## 專案分層架構

專案依照清晰的單向依賴原則劃分：

```text
src/
├─ MinecraftServerManager.App/             WPF 視窗、View、ViewModel、Dialog、佈景主題與組合根
├─ MinecraftServerManager.Core/            業務工作流程、用例（Use Cases）、交易管理與介面合約
├─ MinecraftServerManager.Domain/          領域實體、值物件與純領域邏輯（無外部依賴）
└─ MinecraftServerManager.Infrastructure/  安全檔案系統、網路下載、程序管理、Java 探測與系統整合
tests/
├─ MinecraftServerManager.UnitTests/       領域邏輯與業務流程之單元測試
└─ MinecraftServerManager.IntegrationTests/元件協作與整合驗證測試
```

### 依賴關係規則

```text
App → Core → Domain
App → Infrastructure
Infrastructure → Core Contracts / Domain
Domain （不依賴其他任何專案，純粹領域邏輯）
```

- **Domain**：完全不依賴 WPF、檔案 I/O、網路或作業系統 API，確保領域邏輯的純粹性與可測試性
- **Core**：定義核心服務合約（Contracts）、工作流程（Workflows）與交易編排（Orchestration）
- **Infrastructure**：具體實作 Core 定義之介面，負責實體磁碟存取、外部程序呼叫、HTTP 呼叫與 Java 環境探測
- **App**：負責視窗繪製、使用者互動、ViewModel 狀態管理與依賴注入（Dependency Injection）組合根

## 關鍵技術與安全設計

### 1. 安全檔案系統（SafeFileSystem）

- **路徑邊界防護（Path Containment）**：嚴格驗證所有檔案存取路徑必須落在預期的工作目錄之內，全面阻斷路徑穿越（Directory Traversal）攻擊
- **符號連結防護（Reparse Point Defense）**：在走訪檔案與目錄時，嚴格辨識並攔截惡意符號連結與 NTFS 節點（Junction），防止意外越界存取
- **目錄清理唯讀屬性防護**：在執行目錄遞迴刪除前，自動清除檔案與子資料夾的 Windows `FileAttributes.ReadOnly` 唯讀屬性，避免權限例外中斷操作
- **受限目錄走訪（Bounded Walk）**：限制最大遍歷深度與檔案總數上限，避免惡意目錄遞迴造成堆疊溢位或資源耗竭
- **安全原子寫入（Atomic File Replacement）**：重要設定檔與資料保存時，先寫入暫存檔案並驗證完整性，再透過檔案系統交易替換目標檔案，防止斷電損壞

### 2. 交易式備份與還原機制（Transactional Restore）

- **隔離解壓驗證**：備份還原時一律先解壓縮至獨立暫存隔離區，並執行路徑邊界與檔案完整性校驗
- **現場日誌安全保護（Live Logs Protection）**：執行目標目錄還原覆蓋前，自動將伺服器現場之 `logs/` 與 `crash-reports/` 暫存隔離；待還原覆蓋成功後自動移回合併，防止還原操作抹除發生崩潰或故障當下的關鍵排查線索
- **前置狀態快照**：執行目標目錄覆蓋前，自動為伺服器現況建立復原快照（Rollback Snapshot）
- **失敗自動回復**：若解壓縮或檔案複製過程遭遇任何例外，立即自動回滾至還原前的快照狀態，確保伺服器永不處於毀損中間態
- **備份上限維護**：內建自動清理原則，維持最新 10 份備份，自動清除過期備份以節省磁碟空間

### 3. 高效能獨立主控台與日誌管線

- **獨立視窗架構**：伺服器啟動後於專屬視窗獨立運作，避免高頻日誌阻礙主介面操作
- **伺服器就緒即時偵測（Server Ready Detection）**：非同步日誌管線持續精確比對伺服器就緒特徵（`"Done ("` / `"Done in "`），於完成啟動時觸發 `ServerReady` 事件並即時解鎖介面操作與狀態卡片
- **50ms 聚合緩衝機制**：採用微批次日誌聚合緩衝器，高負載時合併大量日誌輸出，徹底根除 UI 渲染瓶頸
- **ANSI 終端碼清理**：非同步過濾終端控制色碼，保留純文字內容
- **編譯期正則玩家計數**：利用 `[GeneratedRegex]` 原始碼產生器即時解析玩家加入與離開事件，維護精確在線人數
- **程序優雅關閉與強制終止**：優先向伺服器 stdin 傳送 `stop` 指令並等候程序正常關閉；若超時則透過程序樹強制終止，防止孤兒 Java 程序滯留

### 4. 平行化模組管理與 Modrinth 整合

- **平行化本地掃描**：透過 `Parallel.ForEachAsync` 平行讀取伺服器 `mods` 目錄，快速擷取模組元資料並計算雜湊
- **模組智慧啟閉**：透過標準化副檔名切換（`.jar` 與 `.jar.disabled`）實現無損啟用與停用，並自動處理檔名衝突備份
- **雜湊校驗與安全下載**：下載 Modrinth 線上模組時，強制執行 SHA-512／SHA-1 雙重雜湊比對，確保檔案未被竄改
- **多元清單匯出與原生 XLSX 產生器**：支援將模組清單匯出為純文字（.txt）、JSON（.json）、HTML（.html）與 Excel（.xlsx）格式。其中 XLSX 格式由原生輕量級 `OpenXmlSpreadsheetBuilder` 直接透過 `System.IO.Compression.ZipArchive` 產生，零第三方套件依賴，且檔案完全合規相容 Microsoft Excel 與 LibreOffice

### 5. 伺服器版本與載入器深度偵測管線

- **多層級自動探測**：依序深入探測伺服器根目錄 `version.json`、主程式 JAR 內部 metadata（`version.json` 與 `META-INF/MANIFEST.MF`）、`libraries/` 目錄結構（支援 Paper、Vanilla、Fabric、Quilt、Forge 及帶有 `-beta` 的 NeoForge 發行版本）、Paper 特徵設定檔（`paper-global.yml`、`paper.yml` 等）、啟動腳本（`start_server.bat`/`run.bat`/`win_args.txt`）與執行日誌（`logs/latest.log`）
- **精確來源檔案追蹤**：完整記錄 Minecraft 版本、載入器類型與載入器版本個別的確切偵測來源檔案，並於日誌中輸出結構化稽核紀錄
- **伺服器整體大小安全計算**：在背景安全遍歷伺服器目錄累加檔案大小（自動略過 Reparse Point），以高效率格式化為 MB／GB 呈現

### 6. PaperMC 整合與外掛伺服器支援架構

- **官方 Fill API v3 規範串接**：採用 PaperMC 官方最新 `fill.papermc.io/v3` API。動態查詢 PaperMC 支援的 Minecraft 版本清單、特定版本之建置號（Builds）與各項 SHA-256 驗證雜湊。
- **純插件核心架構與單一 JAR 佈署**：PaperMC 核心包含完整的 Paperclip 啟動器，建立時直接下載為 `paper.jar`（或版本命名檔名）並校驗 SHA-256 完整性，免除一般模組載入器（如 Forge/Fabric）需啟動本機外部 Java 安裝程序的開銷。
- **外掛伺服器邊界隔離**：PaperMC 為標準 Bukkit/Spigot/Paper 外掛伺服器架構（放置於 `plugins/`），無法直接相容 Forge/Fabric 模組；模組管理面板自動排除 Paper 伺服器，防止誤操作。
- **標準無圖形介面啟動參數（`--nogui`）**：針對 Paper 伺服器核心自動配置 Paper 官方標準啟動引數 `--nogui`，確保控制台與即時就緒日誌（`"Done ("` / `"Done in "`）無縫相容。

### 7. 雙版本原生單一檔案發布與微軟瘦身技術

- **原生 Single-File 封裝**：直接使用 .NET 官方提供之 Single-File 封裝技術，產出單一可執行檔
- **雙版本發布策略**：
  - **`MinecraftServerManager-self-contained.exe`（獨立自包含版）**：包含完整 .NET 10 Runtime 與所有必要原生函式庫，並啟用微軟官方原生單檔壓縮（`EnableCompressionInSingleFile=true`），總體積約 62 MB，具備最高穩定性與隨點即開特性
  - **`MinecraftServerManager-framework-dependent.exe`（框架相依版）**：僅包含應用程式編譯中繼資料，體積僅約 1.6 MB，仰賴目標電腦安裝之 .NET 10 Desktop Runtime (x64)

### 8. Java 版本需求動態解析與多層快取

- **官方真實來源唯一依賴**：原版核心直接向 Mojang 官方版本 Manifest 與版本 package JSON 動態取得 `javaVersion.majorVersion`；PaperMC 伺服器則直接向 Paper Fill API v3（`/v3/projects/paper/versions/{version}`）動態取得 `version.java.version.minimum`，徹底杜絕版本硬編碼推算。
- **PaperMC Java 需求整合與啟動背景預熱**：Paper 所需之 Java 最低版本直接整合記錄於 `paper_mc_versions_cache.json` 中，並於程式啟動時由背景預載任務一次性平行處理，日常版本切換、伺服器建立與 Java 自動配對 100% 依賴本地快取；僅於使用者點擊重新載入或有全新發布版本時才執行差異增量更新，杜絕重複頻繁的 API 呼叫。
- **多層級持久化快取**：實作 `IMinecraftJavaRequirementService` 服務，快取檔案儲存於 `Cache/versions/mc_java_requirements_cache.json` 與 `paper_mc_versions_cache.json`，並在啟動時提供非同步平行預載（Preload）機制，離線時亦可直接取用歷史版本快取。
- **本地 Java 智慧自動配對**：建立伺服器時的「自動偵測 Java」功能優先以官方指定的 Java major 版本呼叫 `FindBestMatchAsync`，自動選配本機最適合且相容的 64 位元 Java 執行檔。

- **更新檢查與智慧防呆邊界**：
  - 更新檢查服務具備環境探測機制（`IEnvironmentRuntimeInfo`），會自動偵測系統是否具備 .NET 10 Desktop Runtime
  - 預設一律優先挑選自包含版（`self-contained`）；僅當目前本體即為框架相依版且系統存在執行環境時，才選取框架相依版
  - 當遠端 Release 僅提供框架相依版但本機缺乏執行環境時，強制封鎖自動下載並發出警語導引至發布頁面，杜絕下載後因缺少環境崩潰的問題
- **執行期功能開關裁切（Feature Switches）**：
  - `DebuggerSupport=false`：停用執行期除錯支援
  - `EventSourceSupport=false`：停用非必要之 EventSource 診斷日誌
  - `MetadataUpdaterSupport=false`：停用熱重載中繼資料更新機制
  - `UseSystemResourceKeys=true`：直接使用系統資源鍵值以精簡字串資源
- **防毒相容保證**：嚴禁使用 UPX 等第三方加殼工具，保持二進位格式純正，達到 0 防毒誤報

## 品質保證與建置自動化

專案透過自動化腳本實施嚴格門禁：

```bat
# 執行品質門禁（隱私檢查、格式化驗證、Release 編譯品質分析、全量測試）
pwsh -NoProfile -File scripts\dotnet_quality_gate.ps1

# 發布單一執行檔
pwsh -NoProfile -File scripts\dotnet_publish.ps1 -Configuration Release
```

- **隱私與安全檢查**：整合 Gitleaks 掃描原始碼中的金鑰與敏感資訊
- **程式碼排版與分析**：強制執行 `dotnet format --verify-no-changes` 與 Roslyn Analyzers 靜態程式碼品質檢驗
- **測試隔離原則**：測試案例不得發起真實公網請求、不得開啟互動對話框、不得建立全域 Windows 特殊路徑，所有檔案測試均限定於暫存目錄內執行
