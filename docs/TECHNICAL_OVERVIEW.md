# Minecraft 伺服器管理器技術手冊

本手冊說明 Minecraft 伺服器管理器程式所採用的技術堆疊、分層架構、核心演算法與安全機制。

## 技術堆疊總覽

| 領域 | 技術與元件 | 說明 |
|---|---|---|
| 核心平台 | .NET 10（`net10.0-windows10.0.28000.0`） | 採用微軟現代化框架，全域鎖定 Windows 11 26H2 SDK 10.0.28000.0（`TargetPlatformMinVersion=10.0.19045.0`，最低支援 Windows 10 22H2），提供高效能 JIT 與非同步 I/O |
| 語言標準 | C#（`LangVersion=latest`） | 採用 C# 14 / .NET 10 現代慣用語：`System.Threading.Lock`、集合運算式、Span/Memory API、`[GeneratedRegex]` 與模式比對 |
| 使用者介面 | 原生 WinUI 3（`Microsoft.WindowsAppSDK 2.6.4`） | 現代化 Windows 原生桌面框架，落實 MVVM 模式、XAML `{x:Bind}` 強型別資料繫結與深淺色主題切換 |
| 資料序列化 | `System.Text.Json`（Source Generator） | 高效能唯讀 Span、串流與編譯時期來源產生器（`AppJsonSerializerContext`），零反射開銷且完全符合 Trimming 靜態分析要求 |
| 網路通訊 | `System.Net.Http.HttpClient`（`IHttpPort`） | 集中連線池管理、自動重試預算與完整逾時控制|
| 外部行程管理 | `System.Diagnostics.Process`（`IProcessRunner`） | 非同步串流重新導向、平順停止（Graceful Shutdown）與行程樹強制清理（`Process.Kill(entireProcessTree: true)`） |
| 正規表示式最佳化 | `[GeneratedRegex]` Source Generator | 編譯時期產生比對狀態機，零執行期正規表示式解析開銷|
| 平行運算 | `Parallel.ForEachAsync` | 多核平行化處理模組掃描與檔案雜湊運算|
| 測試驗證 | xUnit、UnitTests、IntegrationTests | 完整本機隔離測試（全量單元與整合測試，包含架構原則測試 A1～A28），無外部網路與使用者環境相依性 |
| 封裝發布 | 原生 Single-File、Partial Trimming、單檔壓縮 | 採用官方原生 Single-File 封裝與 Partial IL Trimming 裁剪技術，產出輕量單一自包含執行檔（`MinecraftServerManager.exe`） |

## 專案分層架構

專案依照清晰的單向相依性原則劃分：

```text
src/
├─ MinecraftServerManager.App/             WinUI 3 視窗、View、ViewModel、Dialog、佈景主題與組合根
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

- **Domain**：完全不相依 WinUI 3、WinRT、檔案 I/O、網路或作業系統 API，確保領域邏輯的純粹性與可測試性
- **Core**：定義核心服務合約（Contracts）、工作流程（Workflows）與交易編排（Orchestration）
- **Infrastructure**：具體實作 Core 定義之介面，負責實體磁碟存取、外部行程呼叫、HTTP 呼叫與 Java 環境探測
- **App**：負責視窗算繪、使用者互動與 ViewModel 狀態管理；透過專屬的組合根（`AppCompositionRoot`）集中裝配所有底層服務、管理連線與行程生命週期。UI 互動一律經由 `IUiService`（`WinUiService` 為唯一實作，例外見第 11 節 A7）。

## 關鍵技術與安全設計

### 1. 安全檔案系統（SafeFileSystem）

- **路徑邊界防護（Path Containment）**：嚴格驗證所有檔案存取路徑必須落在預期的工作目錄之內，全面阻斷路徑穿越（Directory Traversal）攻擊
- **符號連結防護（Reparse Point Defense）**：在走訪檔案與目錄時，嚴格辨識並攔截惡意符號連結與 NTFS 節點（Junction），受限於邊界目錄向上檢查，避免誤殺作業系統層級之掛載點與 AppData
- **目錄清理唯讀屬性防護**：在執行目錄遞迴刪除前，自動清除檔案與子資料夾的 Windows `FileAttributes.ReadOnly` 唯讀屬性，避免權限例外中斷操作
- **受限目錄走訪（Bounded Walk）**：限制最大走訪深度與檔案總數上限，避免惡意目錄遞迴造成堆疊溢位或資源耗竭；容量格式化計算全面採用 `WalkBoundedTree`，杜絕符號連結死循環
- **安全不可部分完成替換（Native Atomic File Replacement）**：重要設定檔與資料儲存時，先寫入暫存檔案並驗證完整性，再透過作業系統原生 `File.Replace` 不可部分完成替換目標檔案，防止斷電損壞並保留安全描述元
- **封存檔高效解壓縮與節流（ArrayPool & Throttled Progress）**：解壓縮流程全面採用 `ArrayPool<byte>.Shared` 消除大型物件堆積（LOH）重複配置，於解壓縮串流迴圈實施 100ms / 1% 節流（Throttling）回報
- **ZIP 伺服器匯入非同步背景保護**：解壓縮與大型檔案複製流程一律透過 `await Task.Run(...)` 派發至背景執行緒非同步運行，徹底杜絕同步 I/O 阻塞 UI 執行緒（DispatcherQueue），確保進度條動畫流暢播放與百分比順暢跳動

### 2. 交易式備份與還原機制（Transactional Restore）

- **隔離解壓縮驗證**：備份還原時一律先解壓縮至獨立暫存隔離區，並執行路徑邊界與檔案完整性校驗
- **現場記錄安全保護（Live Logs Protection）**：執行目標目錄還原覆蓋前，自動將伺服器現場之 `logs/` 與 `crash-reports/` 暫存隔離；待還原覆蓋成功後自動移回合併，防止還原操作抹除發生當機或故障當下的關鍵排查線索
- **前置狀態快照**：執行目標目錄覆蓋前，自動為伺服器現況建立復原快照（Rollback Snapshot）
- **失敗自動回復**：若解壓縮或檔案複製過程遭遇任何例外，立即自動回復至還原前的快照狀態，確保伺服器永不處於毀損中間態
- **備份上限維護**：內建自動清理原則，維持最新 10 份備份，自動清除過期備份以節省磁碟空間

### 3. 伺服器完整性、目錄大小與根目錄遷移

- **啟動檔案檢查（ServerIntegrityService）**：依載入器檢查核心 JAR、啟動腳本及參數檔；缺少必要檔案時在管理清單標示警告並停用啟動操作。
- **目錄大小計算（ServerDirectorySizeService）**：透過 `SafeFileSystem.WalkBoundedTree` 在背景計算伺服器檔案容量，排除 `backups/`，並以短期快取減少重複走訪；計算完成後即時更新列表與底部資訊之「目錄大小」。
- **伺服器根目錄遷移與設定（ServersRootRelocator & SettingsManager）**：
  - 初次選擇與變更存放位置時，`NormalizeServersRootPath` 一律以「所選資料夾\servers」為根目錄（所選資料夾已名為 `servers` 時不再附加）；確定後以 `SetExactServersRoot` 寫入正規化結果。
  - `ServersRootRelocator.ValidateTargetRoot` 判定相同路徑、檔案目標與位於原根目錄內之子目錄；子目錄目標無法遷移，僅修改設定並保留原處資料。選擇遷移時目標資料夾必須為空。
  - 支援同磁碟區原子移動與跨磁碟區複製加驗證後清理，失敗時自動清理不完整目標並保留來源資料，並透過 `AtomicFileWriter` 同步更新 `servers.json` 內之伺服器路徑前綴。
- **外部伺服器匯入模式（ImportTransferMode.Copy / Move）**：`ServerManager.ImportServerAsync` 支援複製與遷移兩種模式；選擇遷移時，僅在完整通過目標匯入、驗證與設定寫入後才安全移除原始來源資料夾或 `.zip` 壓縮檔（原地匯入自動跳過來源移除）。

### 4. 高效能獨立主控台與記錄管線

- **獨立視窗架構**：伺服器啟動後於專屬視窗獨立運作，避免高頻記錄阻礙主介面操作
- **伺服器就緒即時偵測（Server Ready Detection）**：非同步記錄管線持續精確比對伺服器就緒特徵（`"Done ("` / `"Done in "`），於完成啟動時觸發 `ServerReady` 事件並即時解鎖介面操作與狀態卡片
- **微批次記錄聚合與緩衝區池化（Log Buffer Pooling）**：採用通道（Channel）與可重複使用緩衝區消除常態性集合記憶體配置，高負載時合併大量記錄輸出，徹底根除 UI 畫面算繪瓶頸
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

### 6. WinUI 3 視窗生命週期、模態協調與主題管理

- **對話方塊、模態架構與父視窗置中（DialogStackCoordinator & ModalWindowHost）**：
  - 8 個輕量對話方塊採用原生內嵌 `ContentDialog`，透過 `DialogStackCoordinator` 協調佇列；WinUI 同一執行緒同時只能開啟一個 `ContentDialog`（即使位於不同視窗），因此全程式共用主視窗的單一協調器，巢狀對話框會先要求上層隱藏並等待其真正關閉後才顯示（逾時 3 秒保底），上層關閉後再自動重現下層。進度對話框（`OperationProgressDialog`）允許為巢狀對話框暫時讓位，作業完成後若仍被重現則開啟即關閉。不得在 `ContentDialog` 按鈕事件中再開啟其他 `ContentDialog`（如模組清單匯出改為格式對話框關閉後才執行儲存與開啟確認）。支援雙鍵確認與三鍵（是／否／取消，`ConfirmYesNoCancelAsync`）互動。
  - 8 個大型互動視窗（如模組更新、伺服器初始化、玩家管理、匯入伺服器等）與獨立監控主控台採用獨立 WinUI 3 原生視窗，透過 `ModalWindowHost.CenterOnParent` 讀取父視窗與子視窗之 `AppWindow` 位置尺寸及所在螢幕工作區（`DisplayArea.WorkArea`），自動相對於父視窗精準置中並執行螢幕邊界夾限（Clamping），同時協調父子 HWND 綁定、視窗停用與非同步結果回傳。
- **崩潰診斷（CrashDiagnostics）**：WinUI 原生快速失敗（0xC000027B 等）不會觸發任何受控例外處理常式，且使用者電腦可能停用 Windows 錯誤報告服務而無事件紀錄。啟動時於記錄檔目錄寫入 `session.marker`（PID、啟動時間、記錄檔路徑），`ProcessExit` 正常結束時刪除；下次啟動若標記仍在，即記錄「上次未正常結束」並附上上次記錄檔最後 20 行。另訂閱 `FirstChanceException`，僅記錄 UI 執行緒拋出的非取消例外（含 HRESULT 與前 12 個堆疊框架，每次執行上限 300 筆，具重入防護），作為原生閃退前的最後線索。
- **原生檔案與資料夾選取器（Microsoft.Windows.Storage.Pickers）**：全面採用 Windows App SDK 2.6 原生 `FileOpenPicker`、`FileSavePicker` 與 `FolderPicker`，直接透過 `AppWindow.Id` 綁定宿主視窗。
- **視窗外觀與強調色彩服務（TitleBarThemeHelper、AccentColorService & WindowIconHelper）**：
  - `TitleBarThemeHelper`：動態同步深淺色主題下 `AppWindowTitleBar` 右上角視窗控制按鈕（最小化、最大化、關閉）的前景與游標暫留對比色彩。
  - `AccentColorService`：讀取 Windows 系統強調色（`UISettings`）並支援使用者自訂色彩動態覆蓋全域資源字典。
  - `WindowIconHelper`：直接由執行檔內嵌資源載入應用程式圖示並快取指派至所有 `AppWindow`。
- **視窗算繪就緒音效回饋（AudioFeedback）**：藉由 Windows 原生 `MessageBeep` 音效機制精準發聲（Warning / Error / Info / Question），防範視窗在建構時期被 Windows 靜音的問題。
- **深淺色動態主題切換**：全面支援 Light 與 Dark 主題，藉由 `ElementTheme` 與 `<ResourceDictionary.ThemeDictionaries>` 原生切換，所有動態控制項均維持高對比度。

### 7. 名單管理系統架構（Player Management System）

- **核心名冊整合（ServerPlayerConfigStore）**：封裝伺服器四大名單持久化檔案：管理員名單（`ops.json`，含 1～4 級權限與略過人數上限標記）、白名單（`whitelist.json`）、玩家封鎖名冊（`banned-players.json`）與 IP 封鎖名冊（`banned-ips.json`）。
- **離線玩家索引快取（usercache.json）**：主動讀取伺服器內部之 `usercache.json`，在離線或無公網環境下自動解析關聯玩家名稱與 UUID，提供名稱快速自動補完。
- **原子不可分割寫入保證**：名單儲存時一律透過 `AtomicFileWriter` 進行不可分割置換，防止名冊並行編輯損毀。
- **虛擬化長列表、明確格線、欄寬調整與統一單位排序**：全面採用 WinUI 3 原生虛擬化 `ListView` 搭配 `TableListViewItemStyle` 與 `DataGridGridLineBrush` 繪製明確的水平與垂直分隔線；表頭 `SortableTableHeader` 支援滑鼠拖曳分隔線手動調整欄寬，以及雙擊表頭或分隔線直接測量並自動對齊該欄最寬項目；點擊表頭排序時由 `NaturalSortHelper` 自動將容量（B/KB/MB/GB/TB 轉 Bytes）、數量（K/M/萬/億轉數值）與日期時間轉換為統一單位後再比較，不影響 UI 顯示格式。核取方塊直接繫結 ViewModel 屬性，確保記憶體低駐留與捲動高流暢度。

### 8. Java 探測去重與安全邊界防護

- **Oracle Shim 跳板轉發器與 Junction 排除**：在環境變數 `PATH` 與候選目錄掃描中，精準過濾包含 `\Oracle\Java\javapath`、`\Oracle\Java\java8path` 與 `\Common Files\Oracle\Java\` 之目錄，並檢查執行檔 PE 中繼資料之 `shimconsole.exe` / `shim.exe`，徹底杜絕 Java 8 重複項。
- **原生符號連結解析（ResolveLinkTarget）**：利用 .NET 原生 `FileSystemInfo.ResolveLinkTarget(returnFinalTarget: true)` 精準解析實體 JRE 目錄，確保候選路徑之唯一性與真實性。

### 9. 單一檔案自包含發布（Single-File Self-Contained）

- **原生專案級別 Single-File 封裝**：直接於 `MinecraftServerManager.App.csproj` 的 Release 屬性群組設定 `<SelfContained>true</SelfContained>`、`<WindowsAppSDKSelfContained>true</WindowsAppSDKSelfContained>`、`<PublishSingleFile>true</PublishSingleFile>`、`<IncludeAllContentForSelfExtract>true</IncludeAllContentForSelfExtract>`、`<IncludeNativeLibrariesForSelfExtract>true</IncludeNativeLibrariesForSelfExtract>`、`<EnableCompressionInSingleFile>true</EnableCompressionInSingleFile>`、`<PublishTrimmed>true</PublishTrimmed>`（`TrimMode=partial`）與 `<DebugType>none</DebugType>`，並自動過濾未使用的 AI/ML/WebView2 元件與非 `zh-TW` 語系資源。無論執行 `scripts/dotnet_publish.ps1` 或直接使用 `dotnet publish`（.NET 8+ 原生預設 Release）均可產出完全一致的單一自包含執行檔（`MinecraftServerManager.exe`），無需外部安裝 Windows App SDK 或 .NET Runtime。

### 10. 自動化建置與維護工具鏈

- **scripts/lib/Common.ps1**：腳本共用入口，提供環境初始化（UTF-8 主控台、停用 MSBuild 節點重用、錯誤即中止）、版本讀取（`Directory.Build.props`）、sha256sum 相容雜湊檔產生與 Release 必要資產清單；腳本與 workflow 不得自行重複實作。
- **scripts/dotnet_quality_gate.ps1**：嚴格執行的門禁腳本，整合腳本編碼檢查、Gitleaks 隱私安全檢查（`gitleaks dir`）、套件還原、原生排版格式化（本機自動修正，CI 強制無變更）、Release 建置品質分析（0 警告 0 錯誤）與全量測試自動驗證。
- **scripts/dotnet_publish.ps1**：單一檔案自包含發布，執行單檔產物斷言、啟動煙霧測試（`--smoke-test`，本機與 CI 皆執行，僅可用 `-SkipSmokeTest` 略過）與 SHA-256 雜湊產生，不使用第三方加殼工具；SLSA 來源證明由 CI（`build-release.yml`）產生。
- **scripts/extract_release_notes.ps1**：依 `Directory.Build.props` 版本擷取 `CHANGELOG.md` 對應章節，版本號採完整比對（`2.2.1` 不會誤配 `2.2.10`）。
- **發布流程（`build-release.yml`）**：先建立草稿 Release，下載資產完成 SHA-256 與 SLSA 證明端對端驗證後才公開；重新執行時自動清除未完成的草稿，已公開的 Release 禁止覆蓋。
- **Renovate**：.NET 相依（`dotnet-sdk`、`Microsoft.Extensions.*`、`System.*`）限制於 major 10，Windows App SDK 限制於 major 2；新版本需發布滿 3 天才建立 PR（安全性修補除外）；workflow 內釘選的 SBOM Tool 與 Renovate 驗證器版本由 regex 管理器追蹤。

### 11. 共用工具入口與架構規則（A1～A28）

架構規則由 `tests/MinecraftServerManager.UnitTests/Architecture/SharedEntryArchitectureTests.cs` 以靜態原始碼掃描強制執行，測試方法名稱前綴（`A1_`～`A28_`）與下表編號一一對應，白名單與「允許例外」欄同步。`SourceScanner` 預設同時清除註解與字串（比對 API 呼叫），標註「字串」者使用 `preserveStrings: true` 僅清除註解（比對檔名、端點等字串常值）。

呼叫端一律使用下表入口，不得自建相似 helper、直接呼叫底層 API 或複製安全檢查；新增入口或例外須同步更新本表與測試白名單。路徑皆省略 `src/MinecraftServerManager.` 前綴。

| 編號 | 規則 | 統一入口／要求 | 允許例外（白名單） |
| --- | --- | --- | --- |
| A1 | 檔案與目錄 I/O | `SafeFileSystem`（含 `GetAvailableFreeSpace`、受限走訪、唯讀屬性清除）、`AtomicFileWriter`；禁止 `File`、`Directory`、`FileInfo`、`DirectoryInfo`、`FileStream`、`DriveInfo` | `Infrastructure/FileSystem/`、`AtomicFileWriter`、`RotatingFileLoggerProvider`、`HttpDownloadClient`（續傳寫入） |
| A2 | ZIP／JAR | `SafeZipArchive`（逐筆讀取 `ReadEntryBytesBounded`／`ReadEntryTextBounded`）；禁止 `ZipFile`、`new ZipArchive`、`ZipArchiveEntry.Open()` | `SafeZipArchive`、`OpenXmlSpreadsheetBuilder`（記憶體建立 XLSX） |
| A3 | 外部行程 | `IProcessRunner`、`IExternalLauncher`；禁止 `Process.Start`、`new Process`、`ProcessStartInfo` | `ProcessRunner` |
| A4 | HTTP 用戶端 | `IHttpPort`；禁止 `new HttpClient`、`SocketsHttpHandler`、`HttpClientHandler` | `AppCompositionRoot` |
| A5 | JSON | `JsonCodec` + `AppJsonSerializerContext`；禁止 `JsonSerializer`、`JsonDocument`、`new JsonSerializerOptions` | `JsonCodec`、`Core/Ports/IHttpPort.cs` |
| A6 | 正規表示式 | `[GeneratedRegex]`；禁止 `new Regex(` 與 `Regex` 靜態方法 | 無 |
| A7 | UI、對話框、選取器、計時器 | `IUiService`；禁止 `MessageBoxW`、`FileOpenPicker`、`FileSavePicker`、`FolderPicker`、`DispatcherTimer`、`DispatcherQueueTimer`、`new ContentDialog` | `WinUiService`、`App.xaml.cs`、`MainWindow.xaml.cs`、`App/Views/` |
| A8 | unsafe | `src/`、`tests/` 禁止 `unsafe` | 無（自動排除 `obj/`、`bin/`、`.g.cs`） |
| A9 | 分層相依 | Domain 不參照任何專案、不 using `System.IO`／`System.Net`／`System.Diagnostics`；Core 僅參照 Domain、不 using `System.IO`／`System.Net.Http`／`System.Diagnostics`；Infrastructure 不參照 App | 無 |
| A10 | ViewModel 邊界 | `App/ViewModels` 不得持有 `Process`、直接 `File.`／`Directory.` 或 `new HttpClient` | 無 |
| A11 | 雜湊 | `HashCalculator`（`TryResolveAlgorithm`、`IsHexDigest`）；禁止 `SHA256`、`SHA1`、`MD5`、`SHA512`、`IncrementalHash`、`HashAlgorithmName.`、`CryptographicOperations.HashData` | `HashCalculator`、`HttpDownloadClient`（串流同步計算） |
| A12 | 記錄輸出 | `ComponentLogger`／`AppLogging`；禁止 `Console`、`Trace`、`Debug` 直接輸出 | 無 |
| A13 | ViewModel 非同步 | 禁止裸 `_ = XxxAsync(`，統一使用 `ViewModelBase.RunSafeAsync` | 無 |
| A14 | 系統提示音效 | `AudioFeedback`；禁止 `SystemSounds`、`new SoundPlayer` | `AudioFeedback` |
| A15 | 日誌等級 | 禁止 `Debug`／`Trace` 等級（`Logger.Debug(`、`LogTrace(` 等） | 無 |
| A16 | 視窗外觀與強調色 | `TitleBarThemeHelper`、`AccentColorService`、`ModalWindowHost`、`WindowIconHelper`；禁止 `AppWindowTitleBar`、`UISettings`、`SetWindowLongPtrW`、`LoadIconW` | 上述四個服務 |
| A17 | 保留裝置名稱、模組檔名剝除（字串） | `ServerName.IsWindowsDeviceName`、`ModHelpers` | `Domain/ValueObjects/ServerName.cs`、`Core/Mods/ModHelpers.cs` |
| A18 | 例外捕獲 | 禁止無型別 `catch`；一律 `catch (Exception ex)` 或更具體型別 | 無 |
| A19 | 模組副檔名判斷（字串） | `ModHelpers`（`IsJarFileName`、`IsModFileName`、`ToDisabledModFileName` 等） | `ModHelpers`、`Domain/Mods/OnlineModVersion.cs`（相依方向） |
| A20 | Minecraft／PaperMC 版本中繼資料（字串） | `MojangVersionCatalog` 唯一持有版本快取檔名、Mojang Manifest（V2 優先）與 PaperMC 端點 | `MojangVersionCatalog` |
| A21 | P/Invoke | `LibraryImport`／`DllImport` 僅限指定輔助類別 | `App.xaml.cs`、`AudioFeedback`、`TitleBarThemeHelper`、`ModalWindowHost`、`WindowIconHelper`、`WindowLayoutHelper` |
| A22 | 系統資料夾路徑 | `RuntimePaths`；禁止 `Environment.GetFolderPath`、`Path.GetTempPath` | `RuntimePaths` |
| A23 | 路徑 API | `Path.IsPathFullyQualified`、`Path.TrimEndingDirectorySeparator`、`Path.GetFullPath(path, basePath)`；禁止 `IsPathRooted` 與 `TrimEnd` 分隔字元 | `SafeZipArchive`（拒絕具根路徑項目） |
| A24 | 進度轉接 | Core／Infrastructure 使用 `SynchronousProgress<T>`，禁止 `new Progress<T>` | 無 |
| A25 | 表格排序 | `TableSortExtensions.SortBy`（內部 `WindowsNaturalSortComparer` 與 `CompareOptions.NumericOrdering`）；禁止 `new WindowsNaturalSortComparer` | `NaturalSortHelper`、`TableSortExtensions` |
| A26 | 暫存檔命名（字串） | `AtomicFileWriter.CreateTempSiblingPath`／`TempFileExtension` | `AtomicFileWriter` |
| A27 | ANSI 清洗與記憶體參數（字串） | `ModHelpers.StripColorAndFormattingCodes`、`MemoryUtils`（`ApplyMemoryFlags`、`ResolveEffectiveMinMemoryMb`） | `ModHelpers`、`Core/Utilities/MemoryUtils.cs` |
| A28 | 載入器種類解析 | `LoaderKinds.TryParse`／`ParseOrDefault`；禁止 `Enum.TryParse<LoaderKind>` | `Domain/Servers/LoaderKinds.cs` |

補充：`SafeFileSystem.IsPathWithin` 另拒絕跨磁碟機與 UNC 目標；XLSX 文字清洗以 `Rune` 逐純量值判斷，保留 emoji 等合法代理字對。
