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
- **受限目錄走訪（Bounded Walk）**：限制最大遍歷深度與檔案總數上限，避免惡意目錄遞迴造成堆疊溢位或資源耗竭
- **安全原子寫入（Atomic File Replacement）**：重要設定檔與資料保存時，先寫入暫存檔案並驗證完整性，再透過檔案系統交易替換目標檔案，防止斷電損壞

### 2. 交易式備份與還原機制（Transactional Restore）

- **隔離解壓驗證**：備份還原時一律先解壓縮至獨立暫存隔離區，並執行路徑邊界與檔案完整性校驗
- **前置狀態快照**：執行目標目錄覆蓋前，自動為伺服器現況建立復原快照（Rollback Snapshot）
- **失敗自動回復**：若解壓縮或檔案複製過程遭遇任何例外，立即自動回滾至還原前的快照狀態，確保伺服器永不處於毀損中間態
- **備份上限維護**：內建自動清理原則，維持最新 10 份備份，自動清除過期備份以節省磁碟空間

### 3. 高效能獨立主控台與日誌管線

- **獨立視窗架構**：伺服器啟動後於專屬視窗獨立運作，避免高頻日誌阻礙主介面操作
- **50ms 聚合緩衝機制**：採用微批次日誌聚合緩衝器，高負載時合併大量日誌輸出，徹底根除 UI 渲染瓶頸
- **ANSI 終端碼清理**：非同步過濾終端控制色碼，保留純文字內容
- **編譯期正則玩家計數**：利用 `[GeneratedRegex]` 原始碼產生器即時解析玩家加入與離開事件，維護精確在線人數
- **程序優雅關閉與強制終止**：優先向伺服器 stdin 傳送 `stop` 指令並等候程序正常關閉；若超時則透過程序樹強制終止，防止孤兒 Java 程序滯留

### 4. 平行化模組管理與 Modrinth 整合

- **平行化本地掃描**：透過 `Parallel.ForEachAsync` 平行讀取伺服器 `mods` 目錄，快速擷取模組元資料並計算雜湊
- **模組智慧啟閉**：透過標準化副檔名切換（`.jar` 與 `.jar.disabled`）實現無損啟用與停用，並自動處理檔名衝突備份
- **雜湊校驗與安全下載**：下載 Modrinth 線上模組時，強制執行 SHA-512／SHA-1 雙重雜湊比對，確保檔案未被竄改
- **多元清單匯出**：支援將模組清單匯出為純文字（.txt）、JSON（.json）、HTML（.html）與 Excel（.xlsx）等 4 種通用格式

### 5. 伺服器版本與載入器深度偵測管線

- **多層級自動探測**：依序深入探測伺服器根目錄 `version.json`、主程式 JAR 內部 metadata（`version.json` 與 `META-INF/MANIFEST.MF`）、`libraries/` 目錄結構（支援 Vanilla、Fabric、Quilt、Forge 及帶有 `-beta` 的 NeoForge 發行版本）、啟動腳本（`run.bat`/`win_args.txt`）與執行日誌（`logs/latest.log`）
- **精確來源檔案追蹤**：完整記錄 Minecraft 版本、載入器類型與載入器版本個別的確切偵測來源檔案，並於日誌中輸出結構化稽核紀錄
- **伺服器整體大小安全計算**：在背景安全遍歷伺服器目錄累加檔案大小（自動略過 Reparse Point），以高效率格式化為 MB／GB 呈現

### 6. 雙版本原生單一檔案發布與微軟瘦身技術

- **原生 Single-File 封裝**：直接使用 .NET 官方提供之 Single-File 封裝技術，產出單一可執行檔
- **雙版本發布策略**：
  - **`MinecraftServerManager-self-contained.exe`（獨立自包含版）**：包含完整 .NET 10 Runtime 與所有必要原生函式庫，並啟用微軟官方原生單檔壓縮（`EnableCompressionInSingleFile=true`），總體積約 62 MB，具備最高穩定性與隨點即開特性
  - **`MinecraftServerManager-framework-dependent.exe`（框架相依版）**：僅包含應用程式編譯中繼資料，體積僅約 1.6 MB，仰賴目標電腦安裝之 .NET 10 Desktop Runtime (x64)
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
