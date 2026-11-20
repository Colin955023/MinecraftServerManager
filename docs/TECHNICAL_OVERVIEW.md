# Minecraft 伺服器管理器技術手冊

## 技術堆疊

| 領域 | 技術 |
|---|---|
| 平台 | .NET 10、C# 14，僅 Windows 11（版本設定見 `Directory.Build.props`） |
| 介面 | 原生 WinUI 3、CommunityToolkit.Mvvm、`{x:Bind}`、深淺色主題 |
| JSON | `System.Text.Json` 來源產生器（`AppJsonSerializerContext`，見 A5） |
| 網路 | `HttpClient`（經 `IHttpPort`、`HttpUrlPolicy` 只允許 HTTPS 公開位址，見 A4） |
| 行程 | `Process`（經 `IProcessRunner`，見 A3） |
| 正規表示式 | `[GeneratedRegex]` |
| 測試 | xUnit v3、架構規則 A1～A35；不連網 |
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

- **Domain**：不使用 WinUI、檔案 I/O、網路或系統 API。
- **Core**：介面與工作流程。
- **Infrastructure**：實作 Core 介面。
- **App**：`AppCompositionRoot` 裝配服務（A33）；UI 互動與檔案 I/O 嚴格經由 Core 介面（見 A7、A29）。
- **大型頁面**：一個區塊一個子 ViewModel，由父 ViewModel 組合與釋放（`ManageServerViewModel` → `List`、`Lifecycle`、`Backup`、`ServersRoot`，由 `PageViewModelFactory` 建立，見 A31；`ModsViewModel` → `Local`、`Online`、`Queue`、`Updates`，共用 `ModsContext`）。
- **連續請求**：版本清單等會競態的載入用 `SerialCancellation`，只套用最新請求的結果。

## 關鍵設計

### 1. 安全檔案系統（SafeFileSystem）

- **路徑邊界**：存取路徑必須在預期目錄內。
- **符號連結與 Junction**：走訪時攔截。
- **受限走訪**：限制項目數與總大小（`EnumerateBoundedTree`）。
- **原子寫入**：`AtomicFileWriter` 先寫暫存檔再替換；不可靜默失敗的檔案用 `WriteTextOrThrow`／`WriteJsonOrThrow`。
- **移動**：`MovePath`、`MoveWithin`、`MoveWithinStrict` 共用 `MoveCore`，檔案被短暫鎖定時重試。
- **ZIP**：`SafeZipArchive` 驗證成員數、大小、符號連結與路徑衝突；壓縮比只檢查超過 64 MB 的成員。

### 2. 備份與還原

- 還原先解壓至暫存區並驗證。
- 覆蓋前建立快照；失敗時清除已搬入的內容並搬回原檔，回復未完成則保留快照。
- 還原前暫存 `logs/`、`crash-reports/`，完成後合併移回。
- 保留份數可設定，超過即刪最舊。
- 執行中的伺服器不可備份。
- 啟動前自動備份：設定 `auto_backup_before_start`。

### 3. 伺服器管理

- **完整性（`ServerIntegrityService`）**：依載入器檢查核心檔案，缺少時停用啟動。
- **目錄大小（`ServerDirectorySizeService`）**：背景計算，排除 `backups/`。
- **根目錄遷移（`ServersRootRelocator`）**：根目錄為「所選資料夾\servers」；目標必須為空；失敗自動回復。已複製到新位置但原位置刪不掉的項目視為完成，並回報殘留路徑。
- **設定檔損毀保護**：`servers.json`、`user_settings.json` 無法解析時先另存為 `.bad`。
- **`ServerManager`**：建立、刪除、更新、掃描；伺服器清單檔由 `ServerRegistryStore`、匯入由 `ServerImportWorkflow` 負責。首次存取時清理未完成的暫存目錄，未完成還原的快照則保留。
- **匯入**：已有同名非空資料夾時拒絕；遷移模式在全部成功後才移除來源。來源為磁碟根目錄、存放根目錄或其上層時拒絕。

### 4. 執行階段與監控

- **多伺服器**：每台一個 `IServerRuntime`，由 `IServerRuntimeHost` 管理。
- **就緒偵測**：輸出不分大小寫含 `"Done ("` 或 `"Done in "` 即設 `IsReady` 並觸發 `ServerReady`。
- **啟動前檢查（`ServerStartPreflight`）**：連接埠衝突與啟動前自動備份。
- **平順停止（`ServerStopCoordinator`）**：送 `stop` 後等待 `ServerDefaults.GracefulStopTimeout`，逾時由使用者決定。
- **遺留行程（`RunningServerRegistry`）**：以 PID 與啟動時間登記，下次啟動時偵測並可終止。
- **記錄管線**：`LogLineBuffer` 由 UI 計時器批次排出；`ServerLogReader` 讀 `logs/latest.log` 尾端。
- **啟動腳本（`StartScriptWriter`）**：`start_server.bat` 與 `user_jvm_args.txt` 只由此寫入；Java 一律用絕對路徑。
- **JVM 參數**：可執行外部命令的選項（`JvmOptionPolicy.IsCommandExecutionOption`）一律拒絕，`ServerLaunchPlanner` 對 JAR 與腳本啟動皆先檢查。`-javaagent` 刻意允許（authlib-injector 等用途；權限等同伺服器 JAR 與模組）。
- **行程結束**：`WaitForExitAsync` 的等待者共用同一個結束工作；伺服器自行結束時由 `ServerRuntime` 釋放資源。
- **Java 版本**：只依 Mojang 官方 JSON（`javaVersion.majorVersion`／`java_version.major`）取得或快取，未標註的舊版為 Java 8。

### 5. 模組管理

- **掃描**：平行讀取 `mods` 目錄並計算雜湊；以世代編號捨棄過期結果。
- **`FlexVersion`**：移植自 Prism Launcher（GPL-3.0-only，見 `COPYING.md`）。
- **下載來源**：必須是官方 Modrinth CDN 且有雜湊值。
- **下載（`HttpDownloadClient`）**：逾時為閒置逾時；無雜湊也無 ETag 時不續傳。
- **版本清單**：抓取失敗或為空時改用過期快取。
- **載入器安裝器（`LoaderInstallerService`）**：Fabric／Quilt 動態查詢官方 Meta（記憶體快取 1 小時），驗證官方網域並採雜湊校驗（Quilt 優先 Meta `hashes`，其餘取 Maven `.sha256`／`.sha1`），取不到即拒絕；Meta 失敗時改用本機已驗證最新快取，下載驗證後自動清理舊檔（Fabric／Quilt 留最新 1 份，Forge／NeoForge 留最近 5 份）。

### 6. 視窗與主題

- **對話框與大型視窗**：`ContentDialog` 經 `DialogStackCoordinator` 排隊（禁止按鈕事件內巢狀開啟）；大型視窗為獨立 WinUI 視窗，命令內關閉用 `CloseDeferred`，對話視窗訂閱 `RequestClose` 以 `CloseWithResult` 設定結果並延後關閉（入口與規範見 A7、A14、A16）。
- **導覽與表格**：主視窗用 `NavigationView`（匯入與開啟資料夾為動作項目，不改變選取）。表格採虛擬化 `ListView`、`TableFrame`、`TableCell`、`SortableTableHeader`（排序與欄寬見 A25）；各表格以 `TableFrame.SortTarget` 指定排序對象，表頭點選與按兩下由 `SortableTableHeader` 轉交；空狀態由 `TableFrame.IsEmpty`／`EmptyText` 以 `x:Load` 延遲建立。`x:Bind` 靜態路徑最後更新；與雙向 `SelectedItem` 同用的 `ItemsSource` 須為執行個體路徑。
- **鍵盤與無障礙**：`KeyboardAccelerator` 提供 F5、Ctrl+F、Delete（以 `ScopeOwner` 限定清單），清單列 Enter 等同按兩下；無標籤輸入框與核取方塊設 `AutomationProperties.Name`，狀態文字設 `LiveSetting`。
- **共用外觀與按鈕**：圖示加文字用 `IconLabel`、「標籤：值」用 `LabeledValue`，共用版面樣式置於 `App.xaml`。`PrimaryButtonStyle` 與語意色按鈕共用 `SolidButtonTemplate`，懸停／按下以透明度回饋，停用改專用筆刷；紅色僅用於破壞性操作；按鈕順序為主要、次要、取消。
- **視覺語彙與外觀**：採 Mica、系統標題列與主題資源／字階 token（見 A16、A32、A34、A35）。`AccentColorService` 更新 App 專用鍵（`AccentBrush`、`AccentTextBrush` 等）與 CheckBox、RadioButton、ToggleSwitch、HyperlinkButton 輕量樣式鍵（框架鍵僅主題與系統一致時生效），文字以 `EnsureTextContrast` 確保 4.5:1 對比，並先更新 Light 字典避免回退改到 Default 筆刷。`WindowLayoutHelper.SetMinimumSizeDip` 設定最小尺寸（見 A30），對話視窗為預設尺寸 2/3；主控台固定 `RequestedTheme="Dark"` 與 `ConsoleFontFamily`。
- **通知與當機診斷**：`IUiService.ShowNotification` 以 InfoBar 顯示資訊／成功／警告、對話框顯示錯誤；`CrashDiagnostics` 以 `session.marker` 偵測上次異常結束並記錄 UI 執行緒例外。

### 7. 名單管理

- `ServerPlayerConfigStore` 讀寫 `ops.json`、`whitelist.json`、`banned-players.json`、`banned-ips.json`。
- 讀取 `usercache.json` 提供名稱與 UUID 補完。

### 8. Java 偵測

- **Oracle Shim 去重**：過濾 `javapath` 轉接目錄與 shim 執行檔。
- **位元數**：`PortableExecutableInspector` 讀 PE 標頭判斷。
- **快取（`java_candidates_cache.json`）**：檔案未變動時不重新執行 `java -version`。

### 9. 單檔自包含發布

`scripts/dotnet_publish.ps1` 產出 `MinecraftServerManager.exe`。發布屬性與排除清單定義於 `App.csproj`（`PruneUnusedSingleFilePayload`），不用第三方加殼。`_UnusedPayload` 只列實測從未載入的檔案；升級 Windows App SDK 後須比對酬載並重新驗證。

啟動時清除 `%TEMP%\.net\MinecraftServerManager\` 下非目前執行個體的舊解壓資料夾。

### 10. 建置工具鏈

- **`scripts/lib/Common.ps1`**：腳本共用函式；腳本與 workflow 不得重複實作。
- **`scripts/dotnet_quality_gate.ps1`**：編碼、版本、Gitleaks、還原、格式、Release 建置、測試與涵蓋率。
- **`scripts/dotnet_publish.ps1`**：單檔發布、SHA-256；`-SmokeTest` 加跑啟動煙霧測試。
- **`scripts/extract_release_notes.ps1`**：擷取 `CHANGELOG.md` 的目前版本章節，找不到即失敗。
- **CI**：`ci-test.yml`、`codeql.yml`、`oss-scorecard.yml`、`validate-renovate.yml`。
- **發布（`build-release.yml`）**：`master` 手動觸發；資產含 `.exe`、SLSA 證明、SBOM 與 `.sha256`；先建草稿，驗證後公開。
- **自動更新信任邊界**：只接受本專案 GitHub Release 的 HTTPS 資產。`.sha256` 與 `.exe` 同源，只能確認下載完整；Release 啟用不可變發布，發布後資產與 tag 無法替換，且擁有者與協作者帳號皆啟用雙重驗證。程式內不驗證簽章或 SLSA 證明（執行檔未做 Authenticode 簽章），需要時以 `gh attestation verify` 手動驗證。
- **Renovate**：.NET 與 Windows App SDK 不跨 major，新版本滿 3 天才建 PR，並每週維護鎖定檔。

### 11. 共用入口與架構規則（A1～A35）

`SharedEntryArchitectureTests.cs` 以原始碼掃描強制執行下表。標「字串」者連字串內容一併掃描。新增入口或例外須同步更新本表與測試白名單。路徑省略 `src/MinecraftServerManager.` 前綴。

| 編號 | 規則 | 統一入口／要求 | 允許例外（白名單） |
| --- | --- | --- | --- |
| A1 | 檔案與目錄 I/O | `SafeFileSystem`（含 `GetAvailableFreeSpace`、受限走訪、唯讀屬性清除、`TryDeleteFile`、`ReadTailText`、`IsDirectoryEmpty`）、`AtomicFileWriter`；禁止 `File`、`Directory`、`FileInfo`、`DirectoryInfo`、`FileStream`、`DriveInfo` | `Infrastructure/FileSystem/`、`AtomicFileWriter`、`RotatingFileLoggerProvider`、`HttpDownloadClient`（續傳寫入） |
| A2 | ZIP／JAR | `SafeZipArchive`（逐筆讀取 `ReadEntryBytesBounded`／`ReadEntryTextBounded`）；禁止 `ZipFile`、`new ZipArchive`、`ZipArchiveEntry.Open()` | `SafeZipArchive`、`OpenXmlSpreadsheetBuilder`（記憶體建立 XLSX） |
| A3 | 外部行程 | `IProcessRunner`、`IExternalLauncher`；禁止 `Process.Start`、`new Process`、`ProcessStartInfo` | `ProcessRunner`（另實作 `IProcessInspector`） |
| A4 | HTTP 用戶端 | `IHttpPort`；禁止 `new HttpClient`、`SocketsHttpHandler`、`HttpClientHandler` | `AppCompositionRoot` |
| A5 | JSON | `JsonCodec` + `AppJsonSerializerContext`；禁止 `JsonSerializer`、`JsonDocument`、`new JsonSerializerOptions` | `JsonCodec`、`Core/Ports/IHttpPort.cs` |
| A6 | 正規表示式 | `[GeneratedRegex]`；禁止 `new Regex(` 與 `Regex` 靜態方法 | 無 |
| A7 | UI、對話框、選取器、計時器 | `IUiService`；選取器以 `FileTypeChoice` 預設集合（Zip／Jar／JavaExecutable／Json／Html／Xlsx／Text，私有建構）限定副檔名；禁止 `MessageBoxW`、`FileOpenPicker`、`FileSavePicker`、`FolderPicker`、`DispatcherTimer`、`DispatcherQueueTimer`、`new ContentDialog` | `WinUiService`、`App.xaml.cs`、`MainWindow.xaml.cs`、`App/Views/` |
| A8 | unsafe | `src/`、`tests/` 禁止 `unsafe` | 無（自動排除 `obj/`、`bin/`、`.g.cs`） |
| A9 | 分層相依 | Domain 不參照任何專案、不 using `System.IO`／`System.Net`／`System.Diagnostics`；Core 僅參照 Domain、不 using `System.IO`／`System.Net.Http`／`System.Diagnostics`；Infrastructure 不參照 App | 無 |
| A10 | ViewModel 邊界 | `App/ViewModels` 嚴禁持有原生 `Process` 實體 | 無 |
| A11 | 雜湊 | `HashCalculator`（`TryResolveAlgorithm`、`IsHexDigest`）；禁止 `SHA256`、`SHA1`、`MD5`、`SHA512`、`IncrementalHash`、`HashAlgorithmName.`、`CryptographicOperations.HashData` | `HashCalculator`、`HttpDownloadClient`（串流同步計算） |
| A12 | 記錄輸出 | `ComponentLogger`／`AppLogging`；禁止 `Console`、`Trace`、`Debug` 直接輸出 | 無 |
| A13 | ViewModel 非同步 | 禁止裸 `_ = XxxAsync(` 與 `_ = Task.Run(`，統一使用 `ViewModelBase.RunSafeAsync` | 無 |
| A14 | 系統提示音效 | `AudioFeedback`；禁止 `SystemSounds`、`SoundPlayer`、`MessageBeep` | `AudioFeedback` |
| A15 | 日誌等級 | 禁止 `Debug`／`Trace` 等級（`Logger.Debug(`、`LogTrace(` 等） | 無 |
| A16 | 視窗外觀與強調色 | `WindowChromeService`、`AccentColorService`、`ModalWindowHost`、`WindowIconHelper`；禁止 `AppWindowTitleBar`、`UISettings`、`SetWindowLongPtrW`、`LoadIconW` | 上述四個服務 |
| A17 | 保留裝置名稱、模組檔名剝除（字串） | `ServerName.IsWindowsDeviceName`、`ModHelpers` | `Domain/ValueObjects/ServerName.cs`、`Core/Mods/ModHelpers.cs` |
| A18 | 例外攔截 | 禁止無型別 `catch`；一律 `catch (Exception ex)` 或更具體型別 | 無 |
| A19 | 模組副檔名判斷（字串） | `ModHelpers`（`IsJarFileName`、`IsModFileName`、`ToDisabledModFileName` 等） | `ModHelpers`、`Domain/Mods/OnlineModVersion.cs`（相依方向） |
| A20 | Minecraft／PaperMC 版本中繼資料（字串） | `MojangVersionCatalog` 唯一持有版本快取檔名、Mojang Manifest（V2 優先）與 PaperMC 端點 | `MojangVersionCatalog` |
| A21 | P/Invoke | `LibraryImport`／`DllImport` 僅限指定輔助類別 | `App.xaml.cs`、`AudioFeedback`、`ModalWindowHost`、`WindowIconHelper`、`WindowLayoutHelper` |
| A22 | 系統資料夾路徑 | `RuntimePaths`；禁止 `Environment.GetFolderPath`、`Path.GetTempPath` | `RuntimePaths` |
| A23 | 路徑 API | `Path.IsPathFullyQualified`、`Path.TrimEndingDirectorySeparator`、`Path.GetFullPath(path, basePath)`；禁止 `IsPathRooted` 與 `TrimEnd` 分隔字元 | `SafeZipArchive`（拒絕具根路徑項目） |
| A24 | 進度轉接 | Core／Infrastructure 使用 `SynchronousProgress<T>`，禁止 `new Progress<T>` | 無 |
| A25 | 表格排序 | `TableSortExtensions.SortBy` + `TableSortKeys`（對應 `Func<T, object?>`，容量／下載量採原始數值、不用反射）；欄寬自動調整用 `SortableTableHeader.AutoFit` + `SortKeyMap.WithDisplay`；禁止呼叫端直呼 `SortKeyComparer` | `NaturalSortHelper`、`TableSortExtensions` |
| A26 | 暫存檔命名（字串） | `AtomicFileWriter.CreateTempSiblingPath`／`TempFileExtension` | `AtomicFileWriter` |
| A27 | ANSI 清洗與記憶體參數（字串） | `ModHelpers.StripColorAndFormattingCodes`、`MemoryUtils`（`ApplyMemoryFlags`、`ResolveEffectiveMinMemoryMb`、`CheckServerMemory` 統一記憶體驗證） | `ModHelpers`、`Core/Utilities/MemoryUtils.cs` |
| A28 | 載入器種類解析 | `LoaderKinds.TryParse`／`ParseOrDefault`；禁止 `Enum.TryParse<LoaderKind>` | `Domain/Servers/LoaderKinds.cs` |
| A29 | 呈現層檔案 I/O | `App/ViewModels`、`App/Views` 須經由 `ILocalFileSystem`、`IServerLogReader`、`IModFileService`、`IServersRootService`、`IServerBackupService`（備份摘要、目的地驗證、檔名產生）；禁止 `SafeFileSystem.`、`ModFileInstaller.`、`ServersRootRelocator.`、`PropertiesDocumentCodec.` | 無 |
| A30 | 視窗尺寸 | `WindowLayoutHelper.ResizeToDip`（邏輯像素依視窗 DPI 換算實體像素）；禁止直接呼叫 `AppWindow.Resize` | `WindowLayoutHelper`、`MainWindow.xaml.cs`（還原使用者視窗大小） |
| A31 | 頁面相依集合 | `PageServices` 僅供組合根與頁面工廠；ViewModel 宣告所需的個別相依 | `AppCompositionRoot`、`ViewModels/PageServices.cs`、`ViewModels/PageViewModelFactory.cs` |
| A32 | 視窗材質與標題列 | `WindowChromeService`；禁止直接設定 `SystemBackdrop`、`MicaBackdrop`、`ExtendsContentIntoTitleBar`、`SetTitleBar` | `WindowChromeService` |
| A33 | 有狀態物件建立 | `ServerRegistryStore`、`ServerImportWorkflow`、`ModIndexPersistence`、`ServerRuntime`、`ServerInitializationWorkflow`、`SettingsManager`、`ProcessRunner` 只由組合根或專屬擁有者建立 | `AppCompositionRoot`、`App.xaml.cs`、`PageViewModelFactory`、`ServerManager`、`ServerRuntimeHost`、`LocalModScanner` |
| A34 | XAML 色彩與字級 | 使用主題資源與字階 token；禁止色碼與數值 `FontSize` | `App.xaml`、`Resources/*.xaml` |
| A35 | 圖示 | 使用 `Resources/Glyphs.xaml` 與 `SymbolThemeFontFamily`；XAML 與程式碼後置禁止 emoji 與寫死 Segoe 字型 | 無 |
