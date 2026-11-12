# Minecraft 伺服器管理器技術手冊

技術堆疊、分層架構與安全機制。

## 技術堆疊

| 領域 | 技術 |
|---|---|
| 平台 | .NET 10（`net10.0-windows10.0.26100.0`，`WindowsSdkPackageVersion` 10.0.26100.87，`TargetPlatformMinVersion=10.0.22000.0`，僅 Windows 11），C# 14 |
| 介面 | 原生 WinUI 3（Windows App SDK 元件套件 2.6.5）、MVVM（CommunityToolkit.Mvvm）、XAML `{x:Bind}`、深淺色主題 |
| JSON | `System.Text.Json` 來源產生器（`AppJsonSerializerContext`），無反射、可裁剪 |
| 網路 | `HttpClient`（經 `IHttpPort`）；`HttpUrlPolicy` 只允許 HTTPS 並於連線時驗證解析結果皆為公開位址，單一位址 5 秒未連上即改試下一個（整體連線逾時 20 秒） |
| 行程 | `Process`（經 `IProcessRunner`），平順停止與行程樹終止 |
| 正規表示式 | `[GeneratedRegex]` |
| 測試 | xUnit v3、單元與整合測試、架構規則 A1～A31；全程本機隔離，無網路 |
| 發布 | 單檔自包含、完整裁剪（`MinecraftServerManager.exe`） |

## 專案分層

```text
src/
├─ MinecraftServerManager.App/             WinUI 3 視窗、View、ViewModel、組合根
├─ MinecraftServerManager.Core/            工作流程、使用案例、介面合約
├─ MinecraftServerManager.Domain/          領域實體、值物件、純邏輯
└─ MinecraftServerManager.Infrastructure/  檔案系統、網路、行程、Java 探測
tests/
└─ MinecraftServerManager.UnitTests/
```

相依方向：`App → Core → Domain`、`App → Infrastructure`、`Infrastructure → Core／Domain`；Domain 不相依任何專案。

- **Domain**：不使用 WinUI、檔案 I/O、網路或系統 API。
- **Core**：服務合約與工作流程。
- **Infrastructure**：實作 Core 介面（磁碟、行程、HTTP、Java 探測）。
- **App**：視窗與 ViewModel；`AppCompositionRoot` 裝配所有服務。UI 互動只經 `IUiService`（`WinUiService` 為唯一實作，例外見 A7）；檔案 I/O 只經注入的 Core 連接埠（A29）。
- **大型頁面拆分**：一個區塊一個子 ViewModel，父 ViewModel 負責組合、導覽與對話框，`Dispose` 由父統一轉呼叫。
  - `ManageServerViewModel` → `List`（清單、選取、狀態、目錄大小）、`Lifecycle`（啟動、停止、監控視窗）、`Backup`、`ServersRoot`。頁面由 `PageViewModelFactory`（依 `PageServices`，僅組合根與工廠可見，A31）建立；子 ViewModel 另經 `ServerStopCoordinator`、`ServerStartPreflight` 協作。
  - `ModsViewModel` → `Local`、`Online`、`Queue`（版本挑選、相依解析、批次安裝）、`Updates`（雜湊比對、批次更新）；共用狀態 `ModsContext`，子 ViewModel 互不參照。
  - `ServerInitializationViewModel`：執行初次啟動流程、彙整輸出、倒數關閉。

## 關鍵技術與安全設計

### 1. 安全檔案系統（SafeFileSystem）

- **路徑邊界**：存取路徑必須落在預期目錄內，阻斷路徑穿越。
- **符號連結與 Junction**：走訪時辨識並攔截；僅在邊界內向上檢查，不誤傷系統掛載點。
- **受限走訪**：限制深度與檔案總數（`EnumerateBoundedTree`），避免惡意目錄造成資源耗竭或無窮迴圈。
- **原子替換**：重要檔案先寫暫存檔再以 `File.Replace` 取代，防斷電損壞。`AtomicFileWriter.Write*` 回傳是否成功；登錄檔、啟動腳本與初始設定等不可靜默失敗者用 `WriteTextOrThrow`／`WriteJsonOrThrow`。
- **移動**：`MovePath`、`MoveWithin`、`MoveWithinStrict` 各自負責邊界檢查，實際搬移共用 `MoveCore`，統一套用防毒／索引短暫鎖檔的重試。
- **刪除前清除唯讀屬性**。
- **ZIP 處理**：`ArrayPool<byte>` 緩衝、進度節流（100 ms／1%）；解壓與大檔複製一律 `Task.Run`，不阻塞 UI 執行緒。

### 2. 交易式備份與還原

- 還原先解壓至隔離暫存區並驗證路徑與完整性。
- 覆蓋前建立還原快照；任何例外自動回復：快照完成後才失敗時，先清除已搬入的還原內容再搬回原檔；回復未完成則保留快照目錄供人工復原。
- 還原前暫存 `logs/`、`crash-reports/`，完成後合併移回。
- 保留份數可設定（預設 10、範圍 1～100，`ServerBackupService` 以 `retentionCountProvider` 取值），超過即刪最舊。
- 執行中的伺服器不可備份。
- 啟動前自動備份：設定 `auto_backup_before_start`（預設關閉）；伺服器無有效備份資料夾或備份失敗時詢問是否仍要啟動。

### 3. 伺服器管理、完整性與根目錄遷移

- **完整性（`ServerIntegrityService`）**：依載入器檢查核心 JAR、啟動腳本、參數檔；缺少時警告並停用啟動。
- **目錄大小（`ServerDirectorySizeService`）**：背景計算，排除 `backups/`，短期快取，不跟隨符號連結。
- **根目錄遷移（`ServersRootRelocator`）**：根目錄一律為「所選資料夾\servers」（所選資料夾已名為 `servers` 則不再附加）；相同路徑、檔案目標、原根目錄子目錄無法遷移；遷移目標必須為空；同磁碟移動、跨磁碟複製加驗證；失敗自動回復並以 `AtomicFileWriter` 更新 `servers.json` 路徑。
- **登錄檔損毀保護**：`servers.json`、`user_settings.json` 無法解析時先複製為 `.bad` 再以空白／預設值繼續。備份檔名須為「伺服器名稱＋`yyyyMMdd-HHmmss`」，名稱互為前綴的伺服器不會誤刪彼此備份。
- **`ServerManager` 職責**：建立、刪除、更新、掃描；登錄檔由 `ServerRegistryStore`、匯入由 `ServerImportWorkflow`、共用輔助由 `ServerSetupHelpers`。讀取於背景執行緒；首次存取時於背景清理未完成刪除墓碑（`.msm-deleting-*`）與純中繼暫存目錄（`.msm-create-staging-*`、`.msm-import-staging-*`、`.msm-restore-staging-*`），若發現未完成還原之快照（`.msm-restore-rollback-*`、`.msm-restore-preserved-logs-*`）則記錄警告並完整保留。
- **匯入**：存放目錄內已有同名且非空的資料夾時拒絕匯入（失敗清理只處理本流程搬入的內容）；複製或遷移（`ImportTransferMode`）；遷移僅在匯入、驗證、寫入設定全部成功後才移除來源資料夾或 `.zip`；原地匯入跳過移除。

### 4. 執行階段、監控與啟動檢查

- **多伺服器**：每台伺服器各一個 `IServerRuntime`，由 `IServerRuntimeHost`（`ServerRuntimeHost`）依名稱（不分大小寫）管理，可同時執行；每台有各自的監控視窗，主視窗關閉時一併關閉。
- **就緒偵測**：輸出不分大小寫含 `"Done ("` 或 `"Done in "` 即設 `IsReady` 並觸發 `ServerReady`。
- **啟動前置檢查（`ServerStartPreflight`）**：比對其他執行中伺服器的 `server-port`（未設定視為 25565，只比連接埠），相同則阻擋；再依設定執行啟動前自動備份。
- **平順停止（`ServerStopCoordinator`）**：送 `stop` 後等待 60 秒（`ServerDefaults.GracefulStopTimeout`），逾時由使用者選「繼續等待」或「強制終止」，不自動強制終止；清單狀態顯示「停止中」。關閉主視窗時若有伺服器執行，先確認並停止全部，取消則不關閉。
- **遺留行程偵測（`RunningServerRegistry`）**：啟動時以 PID 與行程啟動時間登記於 `running_servers.json`，結束時移除；下次啟動比對 PID＋啟動時間（防 PID 重用），偵測到存活的遺留行程時提示並可終止行程樹（`IProcessInspector`）。
- **記錄管線**：`LogLineBuffer`（有界 Channel，滿載捨棄最舊）由 UI 計時器批次排出；監控主控台超過 2200 行修剪至 1800 行；初始化視窗每次最多 500 行。`ServerLogReader` 於背景讀 `logs/latest.log` 尾端最多 2 MB／2500 行，並清除色碼。
- **玩家計數**：`[GeneratedRegex]` 比對加入、離開與人數行，錨定於僅由方括號群組組成的日誌前綴（如 `[12:00:00] [Server thread/INFO]:`），聊天內容無法偽造；支援 `.` 開頭的基岩版名稱。
- **啟動腳本（`StartScriptWriter`）**：`start_server.bat` 與 `user_jvm_args.txt` 只由此寫入；含空白的 JVM 參數自動加引號；Java 路徑須通過 `SafeScriptValidator.IsSafeJavaExecutable`，拒絕純 `java`／`java.exe`，一律使用已解析的絕對路徑；允許 `chcp 65001 > nul` 這類字碼頁切換，攔截其他管線與重導向。可執行外部命令或載入原生程式庫的 JVM 選項（`JvmOptionPolicy.IsCommandExecutionOption`：`-XX:OnError`、`-XX:OnOutOfMemoryError`、`-agentpath`、`-agentlib`、`-Xbootclasspath`）於腳本驗證、啟動規劃與 JVM 參數設定三處一律拒絕。
- **行程結束**：`IManagedProcess.WaitForExitAsync` 的所有等待者共用同一個結束工作並留存結束結果；伺服器自行結束時由 `ServerRuntime` 釋放行程資源。
- **Forge／NeoForge**：GC、記憶體與自訂 JVM 參數寫入 `user_jvm_args.txt`；`run.bat` 啟動時由 Java 路徑推導 `JAVA_HOME` 並將其 `bin/` 置於 `PATH` 最前。
- **Java 版本**：僅依 Mojang 官方 JSON（`javaVersion.majorVersion`／`java_version.major`，未標註的舊版為 `jre-legacy`＝Java 8）取得或快取，不以版本號寫死推算。

### 5. 模組管理、Modrinth 與 FlexVersion

- **平行掃描**：`Parallel.ForEachAsync` 讀 `mods` 目錄並計算雜湊；以世代編號標記載入，切換伺服器後的舊結果直接捨棄。
- **`FlexVersion`**：移植自 Prism Launcher（GPL-3.0-only，版權聲明見 `FlexVersion.cs` 與 `COPYING.md`），支援多區段版本、前導零正規化、忽略 `+` 建置中繼資料、預發布降級比較與模組版本字串正規化。
- **下載來源**：`ModFileInstaller.InstallRemoteModAsync` 強制驗證為官方 Modrinth CDN 且必須提供雜湊值（SHA-512／SHA-1），缺一即拒絕下載。
- **下載逾時與續傳（`HttpDownloadClient`）**：`HttpDownloadOptions.Timeout` 為閒置逾時（每收到資料即重新計時）；既無預期雜湊也無 ETag 時不續傳，一律重新下載。
- **版本清單後備**：`IHttpPort` 於網路失敗時回傳失敗結果而非擲出，`LoaderCatalogService` 對失敗、空結果與例外一律改用過期快取。

### 6. WinUI 3 視窗、模態與主題

- **對話框**：輕量對話框用 `ContentDialog`，由 `DialogStackCoordinator` 佇列（WinUI 同一執行緒同時只能開一個，故全程式共用主視窗的協調器；巢狀時先隱藏上層、等待關閉〔逾時 3 秒保底〕再顯示，上層關閉後重現）；進度對話框可暫時讓位。不得在 `ContentDialog` 按鈕事件中再開 `ContentDialog`。提供雙鍵確認、自訂按鈕文字的兩鍵選擇（`ConfirmChoiceAsync`，Esc 對應次要按鈕，安全選項置於次要）、三鍵（`ConfirmYesNoCancelAsync`）。
- **大型視窗**：Java 管理、模組更新、安裝清單、版本挑選、名單管理、還原備份、伺服器初始化、屬性設定及監控主控台為獨立 WinUI 視窗，統一經 `ModalWindowHost.ConfigureDialogWindow`（主題、圖示、標題列色、`ResizeToDip`、關閉時 `Bindings.StopTracking()`；可選 `RegisterUnsavedChangesPrompt`）；ViewModel 於命令內要求關閉時一律經 `ModalWindowHost.CloseDeferred` 延後關閉（同步關閉會在命令結束更新按鈕狀態時造成原生閃退）；`CenterOnParent` 依父視窗與螢幕工作區置中並夾限。維持 `GWLP_HWNDPARENT` 與 `EnableWindow` 停用父視窗（`OverlappedPresenter.IsModal` 與可最小化子視窗不符，故不採用）。
- **圖示**：`ContentPresenter` 搭配 `ColorIcons.xaml` 的 `DataTemplate`。
- **表格**：虛擬化 `ListView`＋`TableListViewItemStyle`＋`DataGridGridLineBrush`；`TableFrame` 提供表頭列與內容區外框，`TableCell` 提供右側分隔線、單行截斷與 ToolTip；`SortableTableHeader` 支援拖曳調欄寬與按兩下自動對齊；排序由 `TableSortKeys` 提供原始數值，文字用 `NaturalSortHelper`（`CompareOptions.NumericOrdering`）。
- **當機診斷（`CrashDiagnostics`）**：啟動時寫 `session.marker`（PID、啟動時間、記錄檔路徑），正常結束且 PID 相符才刪除；下次啟動若標記仍在且行程已不存在（或 PID 已被晚於標記的行程重用）即記錄「上次未正常結束」；另記錄 UI 執行緒的非取消例外（含 HRESULT 與前 12 個堆疊框架，每次執行上限 300 筆）。
- **選取器**：`Microsoft.Windows.Storage.Pickers` 的 `FileOpenPicker`、`FileSavePicker`、`FolderPicker`，以 `AppWindow.Id` 繫結。
- **外觀服務**：`TitleBarThemeHelper`（標題列按鈕色）、`AccentColorService`（系統強調色用 `AccentLight1`／`AccentDark1`，自訂色計算色階覆蓋資源）、`WindowIconHelper`（內嵌資源圖示）、`AudioFeedback`（`MessageBeep`）。
- **主題**：`ElementTheme` 與 `ThemeDictionaries`，可跟隨系統；狀態色文字以 `ThemeBrush.ForegroundKey` 指定資源鍵。
- **通知（`IUiService.ShowNotification`，擴充方法 `Notify` 套用預設標題）**：`Info`／`Success`／`Warning` 以右上角 `InfoBar` 顯示（最多 4 則；`Warning` 8 秒，其餘 3 秒；滑鼠停留暫停）；`Error` 以 `NotificationDialog` 排隊顯示。分級：前置條件不符、輸入驗證、無可處理項目、自動調整、不影響資料的開啟失敗為 `Warning`；完成為 `Success`；例外或 I/O 失敗為 `Error`；需使用者決定用確認對話框。

### 7. 名單管理

- `ServerPlayerConfigStore` 封裝 `ops.json`（1～4 級與略過人數上限）、`whitelist.json`、`banned-players.json`、`banned-ips.json`；寫入一律經 `AtomicFileWriter`。
- 讀取 `usercache.json` 於離線時關聯名稱與 UUID 並提供自動補完。
- 核取方塊直接繫結 ViewModel。

### 8. Java 探測

- **Oracle Shim 去重**：過濾 `\Oracle\Java\javapath`、`\Oracle\Java\java8path`、`\Common Files\Oracle\Java\`，並檢查 PE 中繼資料中的 `shimconsole.exe`／`shim.exe`。
- **連結解析**：`ResolveLinkTarget(returnFinalTarget: true)` 解析實體 JRE 目錄。
- **位元數**：`PortableExecutableInspector` 以 `PEReader` 讀 PE 標頭的 `Machine` 欄位判斷 32／64 位元；自動更新也以此確認下載檔為合法 PE。
- **快取（`java_candidates_cache.json`）**：記錄路徑、檔案大小、最後修改時間（UTC Ticks），未變動則免啟動 `java -version`。

### 9. 單檔自包含發布

`scripts/dotnet_publish.ps1` 或 `dotnet publish` 皆產出相同的 `MinecraftServerManager.exe`，不需另裝 Windows App SDK 或 .NET。僅參照 `Microsoft.WindowsAppSDK.WinUI`、`.DWrite`、`.Runtime`（Base、Foundation、InteractiveExperiences 由 WinUI 帶入）。單檔屬性只定義於 `App.csproj`，不用第三方加殼。

**發布屬性**

| 屬性 | 值 |
|---|---|
| `SelfContained`、`WindowsAppSDKSelfContained`、`PublishSingleFile`、`IncludeAllContentForSelfExtract`、`EnableCompressionInSingleFile` | `true` |
| `PublishTrimmed` | `true`（`TrimMode=full`） |
| `DebugType` | `none` |

**發布時排除**

| 檔案／類別 | 理由 |
|---|---|
| WebView2、Bootstrap、背景工作、推播通知、`RestartAgent.exe`、MapControl 頁面 | 未使用的 Windows App SDK 元件 |
| 獨立 `Microsoft.UI.Xaml.Controls.pri`、`packages.lock.json`、`app.manifest` | 發布不需要 |
| `Microsoft.UI.Xaml.Phone.dll`、`Microsoft.UI.Designer.dll`、`DWriteCore.dll` | 下列已實測畫面皆未載入；文字繪製用系統 `DWrite.dll` |
| 全部 `.winmd` | 型別中繼資料已由 CsWinRT 編入組件 |
| 散放 `.xaml` | 已編譯為 `.pri` 內的 XBF |
| 非 `zh-TW` 語系資源 | 只提供繁體中文 |
| `System.Xml` | 程式未參照，由裁剪移除（Maven 中繼資料用 `[GeneratedRegex]`，XLSX 串流直寫） |

**已實測未載入**（UIA 樹與模組清單同未裁剪版）：建立、管理、模組、關於與設定等主要畫面；Java 管理、JVM 參數、匯入伺服器、調色盤對話框。

啟動時 `AppCompositionRoot.WarmupAsync` 呼叫 `RuntimePaths.CleanupStaleSingleFileExtractDirectories`，清除 `%TEMP%\.net\MinecraftServerManager\` 下非目前執行個體的舊解壓資料夾。

### 10. 建置與維護工具鏈

- **`scripts/lib/Common.ps1`**：腳本共用入口（環境初始化、版本讀取、sha256sum 相容雜湊檔、`Invoke-SmokeTest`、Release 資產清單）；腳本與 workflow 不得重複實作。
- **`scripts/dotnet_quality_gate.ps1`**：腳本編碼、版本單一事實來源（`App.csproj` 不得重複定義 `<Version>`）、Gitleaks（本機 `gitleaks dir`，CI 用 `gitleaks-action`）、還原、格式（本機自動修正，CI 強制無變更）、Release 建置（0 警告 0 錯誤）、全量測試。測試以 `Microsoft.Testing.Extensions.CodeCoverage` 收集 cobertura，結尾輸出行與分支涵蓋率（依「檔案＋行號」聯集，排除產生碼與測試碼，不設門檻）。
- **`scripts/dotnet_publish.ps1`**：單檔發布、單一 exe 斷言、煙霧測試（`--smoke-test`，CI 以 `GITHUB_ACTIONS` 略過）、SHA-256；SLSA 證明由 CI 產生。
- **`scripts/extract_release_notes.ps1`**：依 `Directory.Build.props` 版本完整比對擷取 `CHANGELOG.md` 章節（`2.2.1` 不誤配 `2.2.10`）。
- **CI**：`ci-test.yml`（Gitleaks、品質門禁、涵蓋率上傳、`publish-check`〔發布與裁剪檢查；煙霧測試為實驗性，`continue-on-error`，視代管執行器是否有互動桌面〕）、`codeql.yml`（每週排程）、`oss-scorecard.yml`（每週排程）、`validate-renovate.yml`。
- **發布（`build-release.yml`）**：僅限 `master` 手動觸發，預檢同一 commit 的 `CI` 與 `CodeQL Analysis (C#)` 已成功；資產為單檔 `.exe`、SLSA 證明（`.intoto.jsonl`）、SPDX 2.2 SBOM（Microsoft SBOM Tool，版本與 SHA-256 釘選）與各自 `.sha256`（`Get-ReleaseAssetNames`）。先建草稿 Release，端對端驗證 SHA-256 與 SLSA 後才公開；重跑清除未完成草稿，禁止覆蓋已公開版本。
- **Renovate**：.NET 相依限 major 10，Windows App SDK 限 major 2，Windows SDK 套件限 `10.0.26100.*`；新版本滿 3 天才建 PR（安全修補除外）。

### 11. 共用入口與架構規則（A1～A31）

`SharedEntryArchitectureTests.cs` 以原始碼掃描強制執行下表（規則表 `Rules`，A9 為獨立測試）。掃描預設清除註解與字串；標「字串」者只清除註解。呼叫端一律使用統一入口，不得自建相似 helper 或直接呼叫底層 API；新增入口或例外須同步更新本表與測試白名單。路徑省略 `src/MinecraftServerManager.` 前綴。

| 編號 | 規則 | 統一入口／要求 | 允許例外（白名單） |
| --- | --- | --- | --- |
| A1 | 檔案與目錄 I/O | `SafeFileSystem`（含 `GetAvailableFreeSpace`、受限走訪、唯讀屬性清除、`TryDeleteFile`、`ReadTailText`、`IsDirectoryEmpty`）、`AtomicFileWriter`；禁止 `File`、`Directory`、`FileInfo`、`DirectoryInfo`、`FileStream`、`DriveInfo` | `Infrastructure/FileSystem/`、`AtomicFileWriter`、`RotatingFileLoggerProvider`、`HttpDownloadClient`（續傳寫入） |
| A2 | ZIP／JAR | `SafeZipArchive`（逐筆讀取 `ReadEntryBytesBounded`／`ReadEntryTextBounded`）；禁止 `ZipFile`、`new ZipArchive`、`ZipArchiveEntry.Open()` | `SafeZipArchive`、`OpenXmlSpreadsheetBuilder`（記憶體建立 XLSX） |
| A3 | 外部行程 | `IProcessRunner`、`IExternalLauncher`；禁止 `Process.Start`、`new Process`、`ProcessStartInfo` | `ProcessRunner`（另實作 `IProcessInspector`） |
| A4 | HTTP 用戶端 | `IHttpPort`；禁止 `new HttpClient`、`SocketsHttpHandler`、`HttpClientHandler` | `AppCompositionRoot` |
| A5 | JSON | `JsonCodec` + `AppJsonSerializerContext`；禁止 `JsonSerializer`、`JsonDocument`、`new JsonSerializerOptions` | `JsonCodec`、`Core/Ports/IHttpPort.cs` |
| A6 | 正規表示式 | `[GeneratedRegex]`；禁止 `new Regex(` 與 `Regex` 靜態方法 | 無 |
| A7 | UI、對話框、選取器、計時器 | `IUiService`；檔案選取器以 `FileTypeChoice` 預設集合（Zip／Jar／JavaExecutable／Json／Html／Xlsx／Text，建構子私有）限定可選副檔名，不提供「所有檔案」；禁止 `MessageBoxW`、`FileOpenPicker`、`FileSavePicker`、`FolderPicker`、`DispatcherTimer`、`DispatcherQueueTimer`、`new ContentDialog` | `WinUiService`、`App.xaml.cs`、`MainWindow.xaml.cs`、`App/Views/` |
| A8 | unsafe | `src/`、`tests/` 禁止 `unsafe` | 無（自動排除 `obj/`、`bin/`、`.g.cs`） |
| A9 | 分層相依 | Domain 不參照任何專案、不 using `System.IO`／`System.Net`／`System.Diagnostics`；Core 僅參照 Domain、不 using `System.IO`／`System.Net.Http`／`System.Diagnostics`；Infrastructure 不參照 App | 無 |
| A10 | ViewModel 邊界 | `App/ViewModels` 嚴禁持有原生 `Process` 實體 | 無 |
| A11 | 雜湊 | `HashCalculator`（`TryResolveAlgorithm`、`IsHexDigest`）；禁止 `SHA256`、`SHA1`、`MD5`、`SHA512`、`IncrementalHash`、`HashAlgorithmName.`、`CryptographicOperations.HashData` | `HashCalculator`、`HttpDownloadClient`（串流同步計算） |
| A12 | 記錄輸出 | `ComponentLogger`／`AppLogging`；禁止 `Console`、`Trace`、`Debug` 直接輸出 | 無 |
| A13 | ViewModel 非同步 | 禁止裸 `_ = XxxAsync(` 與 `_ = Task.Run(`，統一使用 `ViewModelBase.RunSafeAsync` | 無 |
| A14 | 系統提示音效 | `AudioFeedback`；禁止 `SystemSounds`、`SoundPlayer`、`MessageBeep` | `AudioFeedback` |
| A15 | 日誌等級 | 禁止 `Debug`／`Trace` 等級（`Logger.Debug(`、`LogTrace(` 等） | 無 |
| A16 | 視窗外觀與強調色 | `TitleBarThemeHelper`、`AccentColorService`、`ModalWindowHost`、`WindowIconHelper`；禁止 `AppWindowTitleBar`、`UISettings`、`SetWindowLongPtrW`、`LoadIconW` | 上述四個服務 |
| A17 | 保留裝置名稱、模組檔名剝除（字串） | `ServerName.IsWindowsDeviceName`、`ModHelpers` | `Domain/ValueObjects/ServerName.cs`、`Core/Mods/ModHelpers.cs` |
| A18 | 例外攔截 | 禁止無型別 `catch`；一律 `catch (Exception ex)` 或更具體型別 | 無 |
| A19 | 模組副檔名判斷（字串） | `ModHelpers`（`IsJarFileName`、`IsModFileName`、`ToDisabledModFileName` 等） | `ModHelpers`、`Domain/Mods/OnlineModVersion.cs`（相依方向） |
| A20 | Minecraft／PaperMC 版本中繼資料（字串） | `MojangVersionCatalog` 唯一持有版本快取檔名、Mojang Manifest（V2 優先）與 PaperMC 端點 | `MojangVersionCatalog` |
| A21 | P/Invoke | `LibraryImport`／`DllImport` 僅限指定輔助類別 | `App.xaml.cs`、`AudioFeedback`、`ModalWindowHost`、`WindowIconHelper`、`WindowLayoutHelper` |
| A22 | 系統資料夾路徑 | `RuntimePaths`；禁止 `Environment.GetFolderPath`、`Path.GetTempPath` | `RuntimePaths` |
| A23 | 路徑 API | `Path.IsPathFullyQualified`、`Path.TrimEndingDirectorySeparator`、`Path.GetFullPath(path, basePath)`；禁止 `IsPathRooted` 與 `TrimEnd` 分隔字元 | `SafeZipArchive`（拒絕具根路徑項目） |
| A24 | 進度轉接 | Core／Infrastructure 使用 `SynchronousProgress<T>`，禁止 `new Progress<T>` | 無 |
| A25 | 表格排序 | `TableSortExtensions.SortBy` + `TableSortKeys` 型別化排序鍵（欄位名稱對應 `Func<T, object?>`，容量與下載量採原始數值；不使用反射）；欄寬自動調整經 `SortableTableHeader.AutoFit` + `SortKeyMap.WithDisplay` 顯示文字；禁止於呼叫端直接使用 `SortKeyComparer` | `NaturalSortHelper`、`TableSortExtensions` |
| A26 | 暫存檔命名（字串） | `AtomicFileWriter.CreateTempSiblingPath`／`TempFileExtension` | `AtomicFileWriter` |
| A27 | ANSI 清洗與記憶體參數（字串） | `ModHelpers.StripColorAndFormattingCodes`、`MemoryUtils`（`ApplyMemoryFlags`、`ResolveEffectiveMinMemoryMb`、`CheckServerMemory` 統一記憶體驗證） | `ModHelpers`、`Core/Utilities/MemoryUtils.cs` |
| A28 | 載入器種類解析 | `LoaderKinds.TryParse`／`ParseOrDefault`；禁止 `Enum.TryParse<LoaderKind>` | `Domain/Servers/LoaderKinds.cs` |
| A29 | 呈現層檔案 I/O | `App/ViewModels`、`App/Views` 經由 `ILocalFileSystem`、`IServerLogReader`、`IModFileService`、`IServersRootService`、`IServerBackupService`（備份摘要、目的地驗證、檔名產生）；禁止 `SafeFileSystem.`、`ModFileInstaller.`、`ServersRootRelocator.`、`PropertiesDocumentCodec.` | 無 |
| A30 | 視窗尺寸 | `WindowLayoutHelper.ResizeToDip`（邏輯像素依視窗 DPI 換算實體像素）；禁止直接呼叫 `AppWindow.Resize` | `WindowLayoutHelper`、`MainWindow.xaml.cs`（還原使用者視窗大小） |
| A31 | 頁面相依集合 | `PageServices` 僅供組合根與頁面工廠；ViewModel 宣告所需的個別相依 | `AppCompositionRoot`、`ViewModels/PageServices.cs`、`ViewModels/PageViewModelFactory.cs` |
