# Minecraft 伺服器管理器技術手冊

本手冊說明 Minecraft 伺服器管理器程式所採用的技術堆疊、分層架構、核心演算法與安全機制。

## 技術堆疊總覽

| 領域 | 技術與元件 | 說明 |
|---|---|---|
| 核心平台 | .NET 10（`net10.0-windows`） | 採用最新 LTS 框架，提供高效能 JIT 與非同步 I/O |
| 語言標準 | C#（`LangVersion=latest`） | 採用 C# 14 / .NET 10 現代慣用語：`System.Threading.Lock`、集合運算式、Span/Memory API、`[GeneratedRegex]` 與模式匹配 |
| 使用者介面 | WPF（Windows Presentation Foundation） | 原生 Windows 桌面框架，落實 MVVM 模式與資料繫結 |
| 資料序列化 | `System.Text.Json`（Source Generator） | 高效能唯讀 Span、串流與編譯時期來源產生器（`AppJsonSerializerContext`），零反射開銷 |
| 網路通訊 | `System.Net.Http.HttpClient` | 集中連線池管理、自動重試預算與完整逾時控制 |
| 外部行程管理 | `System.Diagnostics.Process` | 非同步串流重新導向、平順停止（Graceful Shutdown）與行程樹強制清理（`Process.Kill(entireProcessTree: true)`） |
| 正規表示式最佳化 | `[GeneratedRegex]` Source Generator | 編譯時期產生比對狀態機，零執行期正規表示式解析開銷 |
| 平行運算 | `Parallel.ForEachAsync` | 多核平行化處理模組掃描與檔案雜湊運算 |
| 測試驗證 | xUnit、UnitTests、IntegrationTests | 完整本機隔離測試，無外部網路與使用者環境相依性 |
| 封裝發布 | 原生 Single-File、官方原生安全壓縮 | 採用官方原生 Single-File 封裝技術，搭配功能開關裁切與單檔壓縮 |

## 專案分層架構

專案依照清晰的單向相依性原則劃分：

```text
src/
├─ MinecraftServerManager.App/             WPF 視窗、View、ViewModel、Dialog、佈景主題與組合根
├─ MinecraftServerManager.Core/            業務工作流程、用例（Use Cases）、交易管理與介面合約
├─ MinecraftServerManager.Domain/          領域實體、值物件與純領域邏輯（無外部相依性）
└─ MinecraftServerManager.Infrastructure/  安全檔案系統、網路下載、行程管理、Java 探測與系統整合
tests/
├─ MinecraftServerManager.UnitTests/       領域邏輯與業務流程之單元測試
└─ MinecraftServerManager.IntegrationTests/元件協作與整合驗證測試
```

### 相依關係規則

```text
App → Core → Domain
App → Infrastructure
Infrastructure → Core Contracts / Domain
Domain （不相依其他任何專案，純粹領域邏輯）
```

- **Domain**：完全不相依 WPF、檔案 I/O、網路或作業系統 API，確保領域邏輯的純粹性與可測試性
- **Core**：定義核心服務合約（Contracts）、工作流程（Workflows）與交易編排（Orchestration）
- **Infrastructure**：具體實作 Core 定義之介面，負責實體磁碟存取、外部行程呼叫、HTTP 呼叫與 Java 環境探測
- **App**：負責視窗繪製、使用者互動與 ViewModel 狀態管理；透過專屬的組合根（`AppCompositionRoot`）集中裝配所有底層服務、管理連線與行程生命週期，並於主視窗顯式啟動流程中完成目錄引導與背景非同步預熱（啟動初期採用 `ShutdownMode.OnExplicitShutdown`，主視窗顯示後切換為 `OnMainWindowClose`，並於主視窗關閉時執行安全關閉），徹底讓 Code-behind 專注於純 UI 邏輯。所有訊息框、檔案選取、對話方塊、進度與視窗控制，以及 UI 執行緒派送與計時器，皆經由 `IUiService` 介面進行（`WpfUiService` 為唯一的 WPF 實作），ViewModel 不直接建立視窗、呼叫 `MessageBox` 或使用 `Dispatcher`；唯一例外為 `App.xaml.cs` 於 `IUiService` 建立之前處理的單一實體提示、啟動失敗與全域未處理例外對話方塊。

## 關鍵技術與安全設計

### 1. 安全檔案系統（SafeFileSystem）

- **路徑邊界防護（Path Containment）**：嚴格驗證所有檔案存取路徑必須落在預期的工作目錄之內，全面阻斷路徑穿越（Directory Traversal）攻擊
- **符號連結防護（Reparse Point Defense）**：在走訪檔案與目錄時，嚴格辨識並攔截惡意符號連結與 NTFS 節點（Junction），受限於邊界目錄向上檢查，避免誤殺作業系統層級之掛載點與 AppData
- **目錄清理唯讀屬性防護**：在執行目錄遞迴刪除前，自動清除檔案與子資料夾的 Windows `FileAttributes.ReadOnly` 唯讀屬性，避免權限例外中斷操作
- **受限目錄走訪（Bounded Walk）**：限制最大走訪深度與檔案總數上限，避免惡意目錄遞迴造成堆疊溢位或資源耗竭；容量格式化計算全面採用 `WalkBoundedTree`，杜絕符號連結死循環
- **安全不可部分完成替換（Native Atomic File Replacement）**：重要設定檔與資料儲存時，先寫入暫存檔案並驗證完整性，再透過作業系統原生 `File.Replace` 不可部分完成替換目標檔案，防止斷電損壞並保留安全描述元
- **封存檔高效解壓縮與節流（ArrayPool & Throttled Progress）**：解壓縮流程全面採用 `ArrayPool<byte>.Shared` 消除大型物件堆積（LOH）重複配置，於解壓縮串流迴圈實施 100ms / 1% 節流（Throttling）回報
- **ZIP 伺服器匯入非同步背景保護**：解壓縮與大型檔案複製流程一律透過 `await Task.Run(...)` 派發至背景執行緒非同步運行，徹底杜絕同步 I/O 阻塞 WPF UI 執行緒（Dispatcher Thread），確保進度條動畫流暢播放與百分比順暢跳動

### 2. 交易式備份與還原機制（Transactional Restore）

- **隔離解壓縮驗證**：備份還原時一律先解壓縮至獨立暫存隔離區，並執行路徑邊界與檔案完整性校驗
- **現場記錄安全保護（Live Logs Protection）**：執行目標目錄還原覆蓋前，自動將伺服器現場之 `logs/` 與 `crash-reports/` 暫存隔離；待還原覆蓋成功後自動移回合併，防止還原操作抹除發生當機或故障當下的關鍵排查線索
- **前置狀態快照**：執行目標目錄覆蓋前，自動為伺服器現況建立復原快照（Rollback Snapshot）
- **失敗自動回復**：若解壓縮或檔案複製過程遭遇任何例外，立即自動回復至還原前的快照狀態，確保伺服器永不處於毀損中間態
- **備份上限維護**：內建自動清理原則，維持最新 10 份備份，自動清除過期備份以節省磁碟空間

### 3. 伺服器完整性與容量檢查

- **啟動檔案檢查（ServerIntegrityService）**：依載入器檢查核心 JAR、啟動腳本及參數檔；缺少必要檔案時在管理清單標示警告並停用啟動操作。
- **目錄容量計算（ServerDirectorySizeService）**：透過 `SafeFileSystem.WalkBoundedTree` 在背景計算伺服器檔案容量，排除 `backups/`，並以短期快取減少重複走訪。

### 4. 高效能獨立主控台與記錄管線

- **獨立視窗架構**：伺服器啟動後於專屬視窗獨立運作，避免高頻記錄阻礙主介面操作
- **伺服器就緒即時偵測（Server Ready Detection）**：非同步記錄管線持續精確比對伺服器就緒特徵（`"Done ("` / `"Done in "`），於完成啟動時觸發 `ServerReady` 事件並即時解鎖介面操作與狀態卡片
- **微批次記錄聚合與緩衝區池化（Log Buffer Pooling）**：採用通道（Channel）與可重複使用緩衝區（`_reusableFlushBatch`）消除計時器常態性集合記憶體配置，高負載時合併大量記錄輸出，徹底根除 UI 畫面算繪瓶頸
- **ANSI 終端機控制碼清理**：非同步過濾終端機控制色碼，保留純文字內容
- **編譯時期正規表示式玩家計數**：利用 `[GeneratedRegex]` 原始程式碼產生器即時解析玩家加入與離開事件，維護精確線上人數
- **行程平順關閉與強制終止**：優先向伺服器 stdin 傳送 `stop` 指令並等候行程正常關閉；若逾時則透過行程樹強制終止，防止孤兒 Java 行程滯留
- **Forge / NeoForge 啟動參數與 Java 環境注入**：
  - 伺服器建立、設定更新與啟動時，自動將推薦之垃圾回收參數、記憶體範圍（`-Xms`、`-Xmx`）與自訂 JVM 參數透過不可分割寫入安全同步至 `user_jvm_args.txt`。
  - 針對 Windows 批次檔啟動方式（`run.bat`），啟動規劃器自動解析指定 Java 實體之根路徑推導 `JAVA_HOME`，並將該 Java `bin/` 目錄插入至執行環境變數 `PATH` 之最前端，直接注入 `ProcessStartSpec`，確保批次檔順暢以使用者指定的精確 Java 版本執行。
- **Java 命令絕對路徑強化與字碼頁重新導向防護（SafeScriptValidator & ServerManager）**：
  - 啟動腳本產生與驗證嚴格落實反向白名單機制，全面拒絕未限定之純 `java` 或 `java.exe` 命令，強制替換為已解析之根目錄化絕對路徑，防範環境變數與 PATH 混淆攻擊。
  - 腳本安全驗證器內建針對合規字碼頁切換輸出重新導向（如 `chcp 65001 > nul` / `chcp 950 >nul`）之安全剝離驗證，既維持對惡意管線與檔案重導向的攔截，又支援批次檔標準語法。

### 5. 平行化模組管理、Modrinth 整合與 FlexVersion 引擎

- **平行化本地掃描與防抖動機制**：透過 `Parallel.ForEachAsync` 平行讀取伺服器 `mods` 目錄，快速擷取模組中繼資料並計算雜湊；模組重新整理內建 300ms 智慧防抖（Debounce），防範介面頻繁觸發時的重度磁碟 I/O 開銷
- **原生 FlexVersion 彈性語意版本比較引擎**：
  - 規格參照開放原始碼專案 Prism Launcher 之版本解析與偏序比較原則，由本專案採用 C# / .NET 10 原生機制（`ReadOnlySpan<char>`、自訂 `Section` 值型別）落實乾淨室獨立實作（Clean-room Implementation），支援多區段語意化版本、前導零正規化、忽略 `+` 建置中繼資料與預發布版降級比較，確保版本新舊判定的數學自反性、反對稱性與傳遞性。
  - 模組更新檢查演算法利用 FlexVersion 全序關係由相容候選集合中判定最大版本（最高相容版本），確保版本決策之單調性與確定性。
- **模組智慧啟閉**：透過標準化副檔名切換（`.jar` 與 `.jar.disabled`）實現無損啟用與停用，並自動處理檔名衝突備份
- **邊下載邊串流增量雜湊校驗（Single-Pass Streaming Hash Verification）**：下載 Modrinth 線上模組與更新資產時，於 HTTP 回應串流寫入本機磁碟的同時透過增量雜湊轉換器同步計算 SHA-512／SHA-256／SHA-1，寫入完成立即驗證，徹底消除下載完成後二次重讀全檔磁碟 I/O 的效能開銷；雜湊不符即主動清理暫存檔。
- **多元清單匯出與原生 XLSX 產生器（ModListExporter & ExportModListViewModel）**：具備專屬互動對話方塊，支援依狀態（包含或排除已停用模組）及相依關係自訂篩選，並將模組清單匯出為純文字（.txt）、JSON（.json）、HTML（.html）與 Excel（.xlsx）格式。其中 XLSX 格式由原生輕量級 `OpenXmlSpreadsheetBuilder` 直接透過 `System.IO.Compression.ZipArchive` 產生，零第三方套件相依性，且檔案完全合規相容 Microsoft Excel 與 LibreOffice。

### 6. 視窗生命週期、前台焦點與全客製化通知架構

- **前台焦點維持（Focus Preservation）**：子對話方塊（如 `ServerInitializationDialog`）關閉或檢視頁面跳轉時，主動透過擁有者視窗啟動機制（`Owner?.Activate()`）維持 WPF 主視窗之前台狀態，防止 Windows 桌面視窗管理員（DWM）因前台暫態失去焦點而將焦點轉移至其他第三方應用程式。
- **淘汰原生 MessageBox 與全 WPF 客製化視窗**：系統淘汰舊式原生 `MessageBox`，全面改由 WPF 原生自訂對話方塊（`CustomConfirmDialog` 與 `NotificationDialog`）負責確認與警示，100% 契合深淺色動態主題。
- **視窗算繪就緒音效回饋（AudioFeedback）**：將 Windows 系統音效呼叫移至對話視窗的 `Loaded` 事件中觸發，並透過安全標準 Windows 音效機制精準發聲（Warning / Error / Info / Question），防範未算繪視窗在建構時期被 Windows 靜音的問題。

### 7. 名單管理系統架構（Player Management System）

- **核心名冊整合（ServerPlayerConfigStore）**：封裝伺服器四大名單持久化檔案：管理員名單（`ops.json`，含 1～4 級權限與略過人數上限標記）、白名單（`whitelist.json`）、玩家封鎖名冊（`banned-players.json`）與 IP 封鎖名冊（`banned-ips.json`）。
- **離線玩家索引快取（usercache.json）**：主動讀取伺服器內部之 `usercache.json`，在離線或無公網環境下自動解析關聯玩家名稱與 UUID，提供名稱快速自動補完。
- **原子不可分割寫入保證**：名單儲存時一律透過 `AtomicFileWriter` 進行不可分割置換，防止名冊並行編輯損毀。
- **高效單次點選 UI 互動與虛擬化回收**：表格採用 `DataGridTemplateColumn` 內嵌 `<CheckBox>`，實現按一下立即切換核取狀態；長列表與表格全面開啟 `EnableRowVirtualization="True"` 與 `VirtualizingPanel.VirtualizationMode="Recycling"`，確保記憶體低駐留與捲動高流暢度。

### 8. Java 探測去重與安全邊界防護

- **Oracle Shim 跳板轉發器與 Junction 排除**：在環境變數 `PATH` 與候選目錄掃描中，精準過濾包含 `\Oracle\Java\javapath`、`\Oracle\Java\java8path` 與 `\Common Files\Oracle\Java\` 之目錄，並檢查執行檔 PE 中繼資料之 `shimconsole.exe` / `shim.exe`，徹底杜絕 Java 8 重複項。
- **原生符號連結解析（ResolveLinkTarget）**：利用 .NET 原生 `FileSystemInfo.ResolveLinkTarget(returnFinalTarget: true)` 精準解析實體 JRE 目錄，確保候選路徑之唯一性與真實性。

### 9. 雙版本原生單一檔案發布

- **原生 Single-File 封裝**：直接於 `MinecraftServerManager.App.csproj` 設定 `<PublishSingleFile>true</PublishSingleFile>`，確保無論透過發布腳本或於 IDE 中直接發布，皆產出標準原生單一可執行檔
- **雙版本發布策略**：
  - **`MinecraftServerManager-self-contained.exe`（獨立自包含版）**：包含完整 .NET 10 Runtime 與所有必要原生函式庫，啟用微軟官方原生單檔壓縮（`EnableCompressionInSingleFile=true`）並僅保留繁體中文與英文之衛星資源組件（`SatelliteResourceLanguages`），具備最高穩定性與隨點即開特性
  - **`MinecraftServerManager-framework-dependent.exe`（框架相依版）**：僅包含應用程式編譯中繼資料，體積極小，仰賴目標電腦安裝之 .NET 10 Desktop Runtime (x64)

### 10. 執行期功能開關裁切（Feature Switches）

以下安全防護與功能開關全量集中宣告於 `MinecraftServerManager.App.csproj`（單一事實來源），確保所有途徑之發布產出皆維持一致：

- `HttpActivityPropagationSupport=false`：停用 HttpClient 內部 OpenTelemetry 分散式追蹤
- `MetricsSupport=false`：停用度量指標系統以降低資源負擔
- `EnableUnsafeBinaryFormatterSerialization=false`、`EnableUnsafeUTF7Encoding=false`：徹底移除過時且具安全隱患的序列化與編碼邏輯
- `StartupHookSupport=false`：停用外部啟動攔截掛鉤檢查，杜絕環境變數注入
- `CustomResourceTypesSupport=false`：停用自訂資源型別序列化功能
- `XmlResolverIsNetworkingEnabledByDefault=false`：停用 XML 外部網路解析器
- `DebuggerSupport=false`：停用執行期除錯支援
- `EventSourceSupport=false`：停用非必要之 EventSource 診斷記錄
- `MetadataUpdaterSupport=false`：停用熱重載中繼資料更新機制

## 品質保證與建置自動化

專案透過自動化腳本實施嚴格門禁：

```bat
# 執行品質門禁（隱私檢查、格式化驗證、Release 編譯品質分析、全量測試）
pwsh -NoProfile -File scripts\dotnet_quality_gate.ps1

# 發布單一執行檔
pwsh -NoProfile -File scripts\dotnet_publish.ps1
```

- **隱私與安全檢查**：整合 Gitleaks 掃描原始程式碼中的金鑰與敏感資訊
- **程式碼排版與分析**：強制執行 `dotnet format --verify-no-changes` 與 Roslyn Analyzers 靜態程式碼品質檢驗
- **測試隔離原則**：測試案例不得發起真實公網請求、不得開啟互動對話方塊、不得建立全域 Windows 特殊路徑，所有檔案測試均限定於暫存目錄內執行
