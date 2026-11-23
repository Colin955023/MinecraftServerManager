# Minecraft 伺服器管理器技術手冊

## 技術堆疊

| 領域 | 技術 |
|---|---|
| 平台 | .NET 10、C# 14，僅 Windows 11（`Directory.Build.props`） |
| 介面 | 原生 WinUI 3、CommunityToolkit.Mvvm、`{x:Bind}`、深淺色主題 |
| JSON | `System.Text.Json` 來源產生器（A5） |
| 網路 | `IHttpPort`；僅 HTTPS 公開位址（A4），停用 Proxy，逐一檢查解析位址 |
| 行程 | `IProcessRunner`、`IExternalLauncher`（A3） |
| 正規表示式 | `[GeneratedRegex]` |
| 測試 | xUnit v3、架構規則 A1～A45；不連網 |
| 發布 | 單檔自包含、完整裁剪 |

## 專案分層

```text
src/
├─ MinecraftServerManager.App/             視窗、View、ViewModel、組合根
├─ MinecraftServerManager.Core/            工作流程、介面
├─ MinecraftServerManager.Domain/          領域實體、值物件、純邏輯
└─ MinecraftServerManager.Infrastructure/  檔案系統、網路、行程、Java 偵測
tests/
└─ MinecraftServerManager.UnitTests/
```

相依方向：`App → Core → Domain`、`App → Infrastructure`、`Infrastructure → Core／Domain`。

- **Domain**：不用 WinUI、檔案 I/O、網路或系統 API。
- **Core**：連接埠介面與工作流程（Java 分 `IJavaRuntimeDetector`／`IJavaInstaller`；行程分 `IProcessRunner`／`IProcessInspector`／`IExternalLauncher`）。
- **Infrastructure**：實作 Core 介面。
- **App**：`AppCompositionRoot` 裝配服務（A33）；UI 與檔案 I/O 經 Core 介面（A7、A29）。
- **大型頁面**：每區塊一個子 ViewModel，由父 ViewModel 組合與釋放（管理頁 `List`／`Lifecycle`／`Backup`／`ServersRoot`；模組頁 `Local`／`Online`／`Queue`／`Updates` 共用 `ModsContext`），由 `PageViewModelFactory` 建立（A31）。
- **連續請求**：會競態的載入用 `SerialCancellation`，只套用最新結果。

## 關鍵設計

### 1. 安全檔案系統（SafeFileSystem）

- 路徑須在預期目錄內；走訪時攔截符號連結與 Junction（`IsReparsePoint` 讀取失敗即拒絕，信任判斷用 `IsConfirmedReparsePoint`）。
- `EnumerateBoundedTree` 限制項目數與總大小。
- `AtomicFileWriter` 先寫暫存檔再替換；不可失敗者用 `WriteTextOrThrow`／`WriteJsonOrThrow`。
- `MovePath`／`MoveWithin`／`MoveWithinStrict` 共用 `MoveCore`，檔案暫時鎖定時重試。
- `SafeZipArchive` 驗證成員數、大小、符號連結與路徑衝突；壓縮比只查超過 64 MB 的成員。

### 2. 備份與還原

- 先解壓至暫存區驗證；覆蓋前建快照，失敗即回復，回復未完成則保留快照。
- 還原前暫存 `logs/`、`crash-reports/`，完成後合併移回。
- 保留份數可設定，超過刪最舊；執行中不可備份；`auto_backup_before_start` 控制啟動前備份。

### 3. 伺服器管理

- **`ServerIntegrityService`**：依載入器檢查核心檔案，缺少即停用啟動。
- **`ServerDirectorySizeService`**：背景計算，僅排除根層 `backups/`，同路徑並發共用結果；大小顯示用 `UnitFormatter.FormatBytes`。
- **`ServersRootRelocator`**：根目錄為「所選資料夾\servers」，目標須為空，失敗自動回復；原位置刪不掉的項目回報殘留路徑。
- **設定檔損毀**：無法解析時以 `SafeFileSystem.TryPreserveCorruptFile` 另存 `.bad`；`server.properties` 用 `PropertiesDocumentCodec`、`ServerPropertiesMetadata`、`ServerPropertiesValidator`。
- **`ServerManager`**：建立、刪除、更新、掃描；清單檔由 `ServerRegistryStore`、匯入由 `ServerImportWorkflow` 負責。首次存取清理未完成暫存目錄。鍵控互斥用 `KeyedAsyncLock`；伺服器目錄經 `ServerSetupHelpers.ResolveServerDirectory` 解析。
- **版本辨識**：`ServerInspector` 依 `version.json`、`MANIFEST.MF` 與載入器函式庫目錄判斷，語意統一用 `MinecraftVersionSemantics`；辨識不出即匯入失敗、掃描略過。
- **匯入**：同名非空資料夾、磁碟根目錄、存放根目錄或其上層皆拒絕；遷移模式全部成功後才移除來源。

### 4. 執行階段與監控

- 每台伺服器一個 `IServerRuntime`，由 `IServerRuntimeHost` 管理。
- **就緒**：輸出不分大小寫含 `"Done ("` 或 `"Done in "` 即設 `IsReady` 並觸發 `ServerReady`。
- **`ServerStartPreflight`**：連接埠衝突與啟動前備份。
- **`ServerStopCoordinator`**：送 `stop` 後等 `ServerDefaults.GracefulStopTimeout`，逾時由使用者決定；`StopAllForShutdownAsync` 供關閉程式與自動更新共用。
- **`RunningServerRegistry`**：以 PID 與啟動時間登記，下次啟動偵測遺留行程。
- **記錄**：`LogLineBuffer` 批次排入 `BulkObservableCollection<string>`；`ServerLogReader` 讀 `latest.log` 尾端；主控台共用 `ConsoleLogListViewStyle` 與 `LogListAutoScroller`。
- **`StartScriptWriter`**：唯一寫入 `start_server.bat`、`user_jvm_args.txt`；Java 用絕對路徑。
- **JVM 參數**：`JvmOptionPolicy.IsRejectedCustomArgument` 為唯一判斷，拒絕可執行外部命令的選項（`@argfile`、`-XX:VMOptionsFile=`、`-javaagent:` 等）與批次檔特殊字元；ViewModel、`ServerManager`、`StartScriptWriter`、`ServerLaunchPlanner` 皆經此檢查。
- **Java 版本**：只依 Mojang 官方 JSON（`javaVersion.majorVersion`／`java_version.major`），未標註者為 Java 8。

### 5. 模組管理

- **掃描**：平行讀取並計算雜湊，世代編號捨棄過期結果，單檔失敗只略過；描述檔依序 `fabric.mod.json`、`quilt.mod.json`、`neoforge.mods.toml`、`mods.toml`、`mcmod.info`。
- **`ModDependencyPlanner`**：只計啟用中模組，不降級，無相容版本即不列入；Quilt 改查 Fabric，NeoForge 1.20.1 改查 Forge。
- **`ModrinthClient`**：JSON 經 `JsonElementReader` 讀取，單筆異常只略過；載入器識別字用 `ModHelpers.ToModrinthLoaderId`，演算法名稱用 `HashAlgorithmNames`。
- **`FlexVersion`**：移植自 Prism Launcher（GPL-3.0-only，見 `COPYING.md`）。
- **下載**：須為官方 Modrinth CDN 且有雜湊；官方來源統一經 `TrustedHostPolicy`。`HttpDownloadClient` 逾時為閒置逾時，無雜湊與 ETag 時不續傳。
- **檔案異動**：同時處理 `.jar`／`.jar.disabled`，限定 `mods` 目錄；匯入先寫暫存再原子替換。
- **`ModListExporter`**：TXT／HTML／JSON／XLSX；JSON 不寫 BOM，XLSX 經 `SanitizeSpreadsheetFormula`。
- **版本清單**：抓取失敗或為空時用過期快取。
- **`LoaderInstallerService`**：Fabric／Quilt 查官方 Meta（快取 1 小時）並驗證網域與雜湊，取不到即拒絕；失敗時用本機已驗證快取。舊安裝器保留 Fabric／Quilt 1 份、Forge／NeoForge 5 份。進度節流用 `ProgressThrottle` 與 `ProgressMapping`。

### 6. 視窗與主題

- **對話框與大型視窗**：`ContentDialog` 經 `DialogStackCoordinator` 排隊（巢狀讓位實作 `INestableContentDialog`）。大型視窗 ViewModel 繼承 `DialogViewModelBase`（需未儲存提示者實作 `IUnsavedChangesPrompt`），標題、尺寸、關閉結果、提示與排序退訂由 `ModalWindowHost.AttachDialog` 處理；命令內關閉用 `CloseDeferred`，延遲初始化用 `RunOnLoadedOnce`（A7、A14、A16、A40）。`TabViewItem` 內容禁用 `x:Load`（不會實體化，且 `Window.Close` 擲 E_POINTER 閃退）。
- **表格**：虛擬化 `ListView`（`TableListViewStyle`）＋ `TableFrame`、`TableCell`、`SortableTableHeader`（A25）。列範本不宣告欄位，由 `TableFrame` 依表頭補齊；晚到的 `Unloaded` 以 `IsLoaded` 略過。`TableFrame.SortTarget` 指定 `TableSortTarget<T>`，重整後自動重套排序。分隔線按兩下自動對齊，Alt+←／→ 調欄寬；最後一欄設 `ShowSplitter="False"` 與 `TableCell.ShowRightBorder="False"`。空狀態用 `IsEmpty`／`EmptyText`，條件為 `UiBindHelpers.IsIdleEmpty` 或 `IsLoadedEmpty`。與雙向 `SelectedItem` 同用的 `ItemsSource` 須為執行個體路徑。
- **鍵盤與無障礙**：F5 重新整理、Delete 刪除（`ScopeOwner` 限定）；清單互動用 `ListViewBehaviors`，文字框用 `TextBoxShortcuts`（`FocusOnCtrlF`、`EnterCommand`），不在 Code-behind 處理按鍵。清單、無標籤輸入框、進度列設 `AutomationProperties.Name`，狀態文字設 `LiveSetting`，裝飾圖示設 `AccessibilityView="Raw"`。
- **共用元件**：`IconLabel`、`IconMessageContent`、`LabeledValue`、`BusyStatusIndicator`；`PrimaryButtonStyle`／`DangerButtonStyle` 共用 `SolidButtonTemplate`。紅色用於刪除、封鎖、停止、重設；按鈕順序為主要、次要、取消。
- **外觀**：Mica、系統標題列、主題資源與字階 token（A16、A32、A34、A35）。`AccentColorService` 更新 App 強調色鍵與常用控制項輕量樣式鍵，文字以 `EnsureTextContrast` 確保 4.5:1。最小尺寸用 `WindowLayoutHelper.SetMinimumSizeDip`（對話視窗為預設尺寸 2/3），邊界用 `GetBounds`（A30）；主控台固定深色。
- **通知與診斷**：`IUiService.ShowNotification`（InfoBar：資訊／成功／警告；對話框：錯誤）；外部開啟用 `UiServiceExtensions.*OrWarn`，停止前檢查用 `EnsureServerStopped`，進度用 `CreateProgress`。`CrashDiagnostics` 以 `session.marker` 偵測異常結束。
- **ViewModel 組裝**：頁面 ViewModel 由 `PageViewModelFactory` 建立；短命對話視窗 ViewModel 由擁有者建立，持有取消權杖者須 `using`。
- **執行緒與取消**：UI 執行緒不做檔案 I/O；設定於 UI 執行緒擷取快照後以 `Task.Run` 寫檔（防抖，關閉前先寫入）。被 await 者以 `when (ex is not OperationCanceledException)` 讓取消上傳，最上層另記錄取消。命令以 `CanExecute` 防重入，確認對話框後重新檢查狀態。

### 7. 名單管理

`ServerPlayerConfigStore` 讀寫 `ops.json`、`whitelist.json`、`banned-players.json`、`banned-ips.json`，並讀 `usercache.json` 補完名稱與 UUID。

### 8. Java 偵測

- 過濾 Oracle `javapath` 轉接目錄與 shim。
- `PortableExecutableInspector` 讀 PE 標頭判斷位元數。
- `java_candidates_cache.json`：檔案未變動不重跑 `java -version`；世代編號確保只有最新一輪寫入。

### 9. 單檔自包含發布

`scripts/dotnet_publish.ps1` 產出 `MinecraftServerManager.exe`；發布屬性與排除清單在 `App.csproj`（`PruneUnusedSingleFilePayload`），不用第三方加殼。`_UnusedPayload` 只列實測未載入的檔案，升級 Windows App SDK 後須重新驗證。啟動時清除 `%TEMP%\.net\MinecraftServerManager\` 下的舊解壓資料夾。

### 10. 建置工具鏈

- **原始碼組織**：大型類別拆為 `<類別>.<職責>.cs`；無實例狀態的邏輯抽成獨立類別。
- **`scripts/lib/Common.ps1`**：腳本共用函式，腳本與 workflow 不得重複實作。
- **`dotnet_quality_gate.ps1`**：編碼、版本一致性（`CHANGELOG.md`、`docs/index.html`）、Gitleaks、鎖定還原、格式、Release 建置、測試與涵蓋率（行 ≥ 80%、分支 ≥ 70%）。
- **`dotnet_publish.ps1`**：單檔發布並顯示 SHA-256；`-SmokeTest` 加跑啟動測試。
- **`extract_release_notes.ps1`**：擷取目前版本 CHANGELOG 章節。
- **測試**：共用替身在 `tests/.../TestSupport`；殼層與時鐘（`TimeProvider`）經建構子注入；非同步呼叫傳 `TestContext.Current.CancellationToken`；命名 `方法_情境_結果`；組合根安全設定由 `CompositionRootConfigurationTests` 驗證。
- **CI**：`ci-test.yml`、`codeql.yml`、`oss-scorecard.yml`、`validate-renovate.yml`。
- **發布（`build-release.yml`）**：僅 `master` 手動觸發，須同 commit 的 CI 與 CodeQL 成功；資產含 `.exe`、SLSA 證明、SBOM 與 `.sha256`；先建草稿，驗證後公開。
- **自動更新**：`GitHubReleaseTrustPolicy` 只接受本專案 GitHub Release 的 HTTPS 資產；下載後驗證 SHA-256 與 x64 執行檔，以 `.new`／`.old` 交換，失敗即還原。執行檔未簽章，需要時以 `gh attestation verify` 手動驗證。
- **Renovate**：.NET 與 Windows App SDK 不跨 major，新版滿 3 天才建 PR，每週維護鎖定檔。

### 11. 共用入口與架構規則（A1～A45）

`SharedEntryArchitectureTests.cs` 以原始碼掃描強制執行下表。標「字串」者連字串內容一併掃描；排除 `bin/`、`obj/` 與自動產生的 `.g.cs`。每條規則附違規樣本驗證；白名單只列實際命中的檔案。新增入口或例外須同步更新本表與測試。路徑省略 `src/MinecraftServerManager.` 前綴。

| 編號 | 規則 | 統一入口／要求 | 允許例外（白名單） |
| --- | --- | --- | --- |
| A1 | 檔案與目錄 I/O | `SafeFileSystem`（含 `GetAvailableFreeSpace`、受限走訪、唯讀屬性清除、`TryDeleteFile`、`ReadTailText`、`IsDirectoryEmpty`）、`AtomicFileWriter`；禁止 `File`、`Directory`、`FileInfo`、`DirectoryInfo`、`FileStream`、`DriveInfo`（含 `IO.`、`System.IO.` 前綴）、`new StreamReader`／`StreamWriter`／`FileSystemWatcher`、`using static System.IO.` | `SafeFileSystem`、`SafeZipArchive`、`AtomicFileWriter`、`RotatingFileLoggerProvider`、`HttpDownloadClient`（續傳寫入）、`OpenXmlSpreadsheetBuilder`（記憶體 ZIP）、`ServerInspector.Memory`、`ServerInspector.VersionDetection`（包覆 SafeFileSystem 串流） |
| A2 | ZIP／JAR | `SafeZipArchive`（逐筆讀取 `ReadEntryBytesBounded`／`ReadEntryTextBounded`）；禁止 `ZipFile`、`new ZipArchive`、`ZipArchiveEntry.Open()`、`ExtractToDirectory`／`ExtractToFile`／`CreateEntryFromFile` | `SafeZipArchive`、`OpenXmlSpreadsheetBuilder`（記憶體建立 XLSX） |
| A3 | 外部行程 | `IProcessRunner`、`IExternalLauncher`；禁止 `Process.Start`、`Process.GetProcessById` 等查詢、`new Process`、目標型別 `Process p = new()`、`ProcessStartInfo` | `ProcessRunner`（另實作 `IProcessInspector`；`CrashDiagnostics` 經 `ProcessRunner.QueryStartTimeUtc`）、`ShellLauncher`（`IExternalLauncher`） |
| A4 | HTTP 用戶端 | `IHttpPort`；禁止 `new HttpClient`、目標型別 `HttpClient c = new()`、`SocketsHttpHandler`、`HttpClientHandler` | `AppCompositionRoot` |
| A5 | JSON | `JsonCodec` + `AppJsonSerializerContext`、`JsonElementReader`；禁止 `JsonSerializer.`、`JsonDocument.`、`JsonNode.Parse`、`new JsonSerializerOptions`、`.Deserialize<`（`JsonCodec` 除外）、`ReadFromJsonAsync`／`GetFromJsonAsync`，與直接呼叫 `.GetString()`／`.GetInt32()`／`.GetInt64()`／`.GetBoolean()` | `JsonCodec`、`JsonElementReader` |
| A6 | 正規表示式 | `[GeneratedRegex]`；禁止 `new Regex(`、目標型別 `Regex r = new(…)` 與 `Regex` 靜態方法（含跨行寫法） | 無 |
| A7 | UI、對話框、選取器、計時器 | `IUiService`；選取器以 `FileTypeChoice` 預設集合（Zip／Jar／JavaExecutable／Json／Html／Xlsx／Text，私有建構）限定副檔名；禁止 `MessageBoxW`、`FileOpenPicker`、`FileSavePicker`、`FolderPicker`、`DispatcherTimer`、`DispatcherQueueTimer`、`new ContentDialog`、直接引用 `DispatcherQueue` 型別 | `WinUiService`、`MainWindow`（`.xaml.cs`、`.Notifications.cs`）、`TableSortExtensions`（控制項經 `element.DispatcherQueue` 存取不在此限） |
| A8 | unsafe | `src/`、`tests/` 禁止 `unsafe` | 無（自動排除 `obj/`、`bin/`、`.g.cs`） |
| A9 | 分層相依 | Domain 不參照任何專案、不使用 `System.IO`／`System.Net`／`System.Diagnostics`；Core 僅參照 Domain、不使用 `System.IO`／`System.Net.Http`／`System.Diagnostics`（含 `global using` 與完整限定名稱，`System.Diagnostics.CodeAnalysis` 除外）；Domain、Core 不得有 `PackageReference`（白名單為空）；Infrastructure 不參照 App | 無 |
| A10 | ViewModel 邊界 | `App/ViewModels` 嚴禁持有原生 `Process` 實體（含 `Process?`、`Process[]`、泛型引數） | 無 |
| A11 | 雜湊 | `HashCalculator`（`TryResolveAlgorithm`、`IsHexDigest`）+ `HashAlgorithmNames`（標準演算法名稱常數）；禁止 `SHA256`、`SHA1`、`MD5`、`SHA512`、`IncrementalHash`、`HashAlgorithmName.`、`CryptographicOperations.HashData` | `HashCalculator`、`HttpDownloadClient`（串流同步計算） |
| A12 | 記錄輸出 | `ComponentLogger`／`AppLogging`；禁止 `Console`（含 `Error`／`Out`）、`Trace`、`Debug`、`Debugger.Log` 直接輸出 | 無 |
| A13 | ViewModel 非同步 | 禁止裸 `_ = XxxAsync(`（含泛型）與 `_ = Task.Run(`，統一使用 `ViewModelBase.RunSafeAsync` | 無 |
| A14 | 系統提示音效 | `AudioFeedback`；禁止 `SystemSounds`、`SoundPlayer`、`MessageBeep` | `AudioFeedback` |
| A15 | 日誌等級 | 禁止 `Debug`／`Trace` 等級（`Logger.Debug(`、`_logger.LogDebug(`、`Log(LogLevel.Trace` 等） | 無 |
| A16 | 視窗外觀與強調色 | `WindowChromeService`、`AccentColorService`、`ModalWindowHost`、`WindowIconHelper`；禁止 `AppWindowTitleBar`、`.TitleBar`、`UISettings`、`SetWindowLongPtrW`、`LoadIconW` | `WindowChromeService`、`AccentColorService` |
| A17 | 保留裝置名稱、模組檔名剝除（字串） | `ServerName.IsWindowsDeviceName`（`CON`、`PRN`、`NUL`、`AUX`、`COM1`、`LPT1`、`CLOCK$` 等）、`ModHelpers` | `Domain/ValueObjects/ServerName.cs`、`Core/Mods/ModHelpers.cs` |
| A18 | 例外攔截 | 禁止無型別 `catch` 與不綁變數且不重拋之吞沒型 `catch (Exception)`（跨行掃描）；一律 `catch (Exception ex)` 或更具體型別 | `RotatingFileLoggerProvider`、`CrashDiagnostics` |
| A19 | 模組副檔名判斷（字串） | `ModHelpers`（`IsJarFileName`、`IsModFileName`、`ToDisabledModFileName` 等） | `ModHelpers`、`Domain/Mods/OnlineModVersion.cs`（相依方向） |
| A20 | Minecraft／PaperMC 版本中繼資料（字串） | `MojangVersionCatalog` 唯一持有版本快取檔名、Mojang Manifest（V2 優先）與 PaperMC 端點 | `MojangVersionCatalog` |
| A21 | P/Invoke | `LibraryImport`／`DllImport`／`static extern` 僅限指定輔助類別 | `App.xaml.cs`、`AudioFeedback`、`ModalWindowHost`、`WindowIconHelper`、`WindowLayoutHelper` |
| A22 | 系統資料夾路徑 | `RuntimePaths`；禁止 `Environment.GetFolderPath`、`Path.GetTempPath` | `RuntimePaths` |
| A23 | 路徑 API | `Path.IsPathFullyQualified`、`Path.TrimEndingDirectorySeparator`、`Path.GetFullPath(path, basePath)`；禁止 `IsPathRooted` 與 `TrimEnd` 分隔字元 | `SafeZipArchive`（拒絕具根路徑項目） |
| A24 | 進度轉接 | 全專案進度轉接、區間換算與節流使用 `SynchronousProgress<T>`、`ProgressMapping`、`ProgressThrottle`；禁止 `new Progress<T>` 與目標型別 `Progress<T> p = new(…)` | 無 |
| A25 | 表格排序 | `TableSortExtensions.SortBy` + `TableSortKeys`（對應 `Func<T, object?>`，容量／下載量採原始數值、不用反射）；欄寬自動調整用 `SortableTableHeader.AutoFit` + `SortKeyMap.WithDisplay`；禁止呼叫端直呼 `SortKeyComparer` | `TableSortExtensions` |
| A26 | 暫存檔命名（字串） | `AtomicFileWriter.CreateTempSiblingPath`／`TempFileExtension` | `AtomicFileWriter` |
| A27 | ANSI 清洗與記憶體參數解析（字串） | `ModHelpers.StripColorAndFormattingCodes`、`MemoryHelpers`（`ApplyMemoryFlags`、`ResolveEffectiveMinMemoryMb`、`CheckServerMemory`、`TryReplaceScriptJvmArgs` 統一記憶體與腳本區段參數處理）；禁止他處以 `[GeneratedRegex]`（含跨行寫法）比對 `\x1B`／`\e`／`-Xmx`（組出啟動參數不在此限） | `Core/Mods/ModHelpers.cs`、`Core/Utilities/MemoryHelpers.cs` |
| A28 | 載入器種類解析 | `LoaderKinds.TryParse`／`ParseOrDefault`；禁止 `Enum.TryParse<LoaderKind>`、`Enum.TryParse(…, out LoaderKind …)` 與 `typeof(LoaderKind)` 解析 | 無 |
| A29 | 呈現層檔案 I/O | `App/ViewModels`、`App/Views`、`App/Controls` 須經由 `ILocalFileSystem`、`IServerLogReader`、`IModFileService`、`IServersRootService`、`IServerBackupService`（備份摘要、目的地驗證、檔名產生），磁碟 I/O 方法皆為非同步；禁止 `SafeFileSystem.`、`SafeZipArchive.`、`AtomicFileWriter.`、`RuntimePaths.`、`ModFileInstaller.`、`ServersRootRelocator.`、`PropertiesDocumentCodec.`、`StartScriptWriter.`、`ServerTombstoneManager.` | 無 |
| A30 | 視窗尺寸 | `WindowLayoutHelper.ResizeToDip`（邏輯像素依視窗 DPI 換算實體像素）與 `WindowLayoutHelper.GetBounds`；禁止直接呼叫 `AppWindow.Resize`／`ResizeClient` | `WindowLayoutHelper` |
| A31 | 頁面相依集合 | `PageServices` 僅供組合根與頁面工廠；ViewModel 宣告所需的個別相依 | `AppCompositionRoot`、`ViewModels/PageServices.cs`、`ViewModels/PageViewModelFactory.cs` |
| A32 | 視窗材質與標題列 | `WindowChromeService`；禁止直接設定 `SystemBackdrop`、`MicaBackdrop`、`ExtendsContentIntoTitleBar`、`SetTitleBar` | `WindowChromeService` |
| A33 | 有狀態物件建立 | `ServerRegistryStore`、`ServerImportWorkflow`、`ModIndexPersistence`、`ServerRuntime`、`ServerInitializationWorkflow`、`SettingsManager`、`ProcessRunner` 只由組合根或專屬擁有者建立（含命名空間前綴與目標型別 `X x = new()` 寫法） | `App.xaml.cs`、`PageViewModelFactory`、`ServerManager`、`ServerRuntimeHost`、`LocalModScanner` |
| A34 | XAML 色彩與字級 | 使用主題資源與字階 token；禁止色碼（含 3／4 位短碼）與數值 `FontSize`（含 `Setter`） | `App.xaml` |
| A35 | 圖示 | 使用 `Resources/Glyphs.xaml` 與 `SymbolThemeFontFamily`；全專案原始碼（Domain／Core／Infrastructure／App）與 XAML 禁止 emoji（文字箭頭 `➔` 除外），App 禁止寫死 Segoe 字型（且 `<FontIcon>` 須顯式指定 `SymbolThemeFontFamily`） | 無 |
| A36 | 載入器檔案配置字串（字串） | 標準檔名由 `ServerDefaults` 常數（`ServerJarFileName`、`RunBatFileName`、`WinArgsFileName`、`LatestLogFileName`、`CrashReportsDirectoryName` 等）提供；禁止他處寫入字面值 `"server.jar"`、`"win_args.txt"`、`"run.bat"`、`"latest.log"`、`"crash-reports"` | `ServerDefaults` |
| A37 | 載入器名稱比較（字串） | Core／Infrastructure 禁以 `Equals`、`StartsWith`、`==`、`case` 比對 `"fabric"`、`"forge"`、`"neoforge"`、`"quilt"`、`"paper"`；改用 `LoaderKind`、`LoaderKinds.TryParseModrinthId`、`LoaderLayout` | `ServerInspector`（啟動 JAR 檔名前綴偵測，非載入器判斷） |
| A38 | 暫時性 I/O 重試 | 禁止手寫 `Thread.Sleep` 重試迴圈；統一使用 `SafeFileSystem.RetryOnTransientIo` | `SafeFileSystem.Operations`（`RetryOnTransientIo` 本體） |
| A39 | 單飛快取 | 禁止 `Lazy<Task<…>>`；統一使用 `SingleFlight<TKey, TValue>` | `SingleFlight` |
| A40 | 對話框關閉繫結 | `App/Views` 禁止直接 `.RequestClose +=`／`-=`；統一使用 `ModalWindowHost.BindRequestClose` | 無 |
| A41 | 外部開啟 | `App/ViewModels` 禁止直呼 `IExternalLauncher.OpenUrl／OpenFolder／OpenFile／ShowInFolder`；統一使用 `UiServiceExtensions` 的 `*OrWarn` 方法 | 無 |
| A42 | 測試衛生 | tests 禁止 `Thread.Sleep(`、無 handler 的 `new HttpClient()`、`Process.Start(` | `TempDirectory`（清除時等待檔案釋放）、`TestJunction`（建立 junction 需啟動 cmd.exe） |
| A43 | 空 catch | 禁止空 `catch` 區塊（含僅註解者）；至少須記錄或重拋 | `RotatingFileLoggerProvider`、`CrashDiagnostics`（日誌器自身失敗無回報管道） |
| A44 | OperationCanceledException | `catch (OperationCanceledException)` 區塊內須 `throw`、記錄（`Logger`／`ComponentLogger`／`AppLogging`）或經 UI 通知（`_ui.`／`Notify`／`Show*`），禁止無聲結束；非呼叫端取消之逾時須重試或回傳失敗並記錄（`when` 排除呼叫端取消） | `HttpUrlPolicy`（單一位址逾時改試下一位址，迴圈末端以 `lastException` 重拋）、`WinUiService`（取消經 `TrySetCanceled` 傳回等待端） |
| A45 | XAML 繫結 | App 專案之 XAML 禁止 `{Binding}`，使用 `{x:Bind}` | 無 |

共用入口登記（新增時同步更新）：

- Domain：`LoaderLayout`（載入器檔案配置）、`ServerDefaults`（標準檔名）、`LoaderKinds`（解析與 Modrinth 識別字對映）、`NumericSegmentComparer`（版本比較）。
- Core：`LoaderCompatibility`（載入器相容性）。
- Infrastructure：`SafeFileSystem.RetryOnTransientIo`（I/O 重試）、`SingleFlight<TKey, TValue>`（同鍵共用結果）、`ServerLaunchPlanner.BuildJvmAndTargetArgs`（啟動參數）、`EphemeralStagingScope`（暫存提交與回滾）。
- App 對話框：`DialogViewModelBase`、`IDialogCloseRequester`、`IUnsavedChangesPrompt`、`INestableContentDialog`、`ModalWindowHost.AttachDialog`／`BindRequestClose`。
- App 控制項：`ListViewBehaviors`、`VisualTreeHelperExtensions`、`BusyStatusIndicator`；`ThemeBrush`（載入與主題變更時重套筆刷）；`InfoBarThemeRefresh`（InfoBar 背景隨主題更新，所有 InfoBar 須設定）；`WheelPassthroughComboBox`（收合時滾輪捲動頁面而非切換選項，所有下拉選單須使用）。
- App 其他：`PageKeys`（頁面鍵）、`ProcessControlExceptions.IsExpected`（行程控制預期例外）、`UiServiceExtensions.*OrWarn`（外部開啟失敗警告）。
