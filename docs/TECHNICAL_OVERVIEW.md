# Minecraft 伺服器管理器技術手冊

## 技術堆疊

| 領域 | 技術 |
|---|---|
| 平台 | .NET 10、C# 14，僅 Windows 11（版本設定見 `Directory.Build.props`） |
| 介面 | 原生 WinUI 3（Windows App SDK `WinUI`／`Runtime` 元件套件）、CommunityToolkit.Mvvm、`{x:Bind}`、深淺色主題 |
| JSON | `System.Text.Json` 來源產生器（`AppJsonSerializerContext`，見 A5） |
| 網路 | `HttpClient`（經 `IHttpPort`、`HttpUrlPolicy` 只允許 HTTPS 公開位址，見 A4；`UseProxy = false`，連線逐一檢查解析後位址） |
| 行程 | `Process`（經 `IProcessRunner`、`IExternalLauncher`，見 A3） |
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

- **Domain**：不使用 WinUI、檔案 I/O、網路或系統 API。
- **Core**：連接埠介面（Java 偵測／安裝分為 `IJavaRuntimeDetector`、`IJavaInstaller`；行程執行／查詢／外部開啟分為 `IProcessRunner`、`IProcessInspector`、`IExternalLauncher`）與工作流程。
- **Infrastructure**：實作 Core 介面。
- **App**：`AppCompositionRoot` 裝配服務（A33）；UI 互動與檔案 I/O 嚴格經由 Core 介面（見 A7、A29）。
- **大型頁面**：一個區塊一個子 ViewModel，由父 ViewModel 組合與釋放（`ManageServerViewModel` → `List`、`Lifecycle`、`Backup`、`ServersRoot`，由 `PageViewModelFactory` 建立，見 A31；`ModsViewModel` → `Local`、`Online`、`Queue`、`Updates`，共用 `ModsContext`）。
- **連續請求**：版本清單等會競態的載入用 `SerialCancellation`，只套用最新請求的結果。

## 關鍵設計

### 1. 安全檔案系統（SafeFileSystem）

- **路徑邊界**：存取路徑必須在預期目錄內。
- **符號連結與 Junction**：走訪時攔截。`IsReparsePoint` 讀取失敗視為 reparse（失敗即拒絕）；需確認為 reparse 才放行的信任判斷（如 WindowsApps 別名）用 `IsConfirmedReparsePoint`。
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
- **目錄大小（`ServerDirectorySizeService`）**：背景計算，只排除根層 `backups/`；同路徑並發請求共用同一次計算。容量與檔案大小顯示統一使用 `UnitFormatter.FormatBytes`。
- **根目錄遷移（`ServersRootRelocator`）**：根目錄為「所選資料夾\servers」；目標必須為空；失敗自動回復。已複製到新位置但原位置刪不掉的項目視為完成，並回報殘留路徑。
- **設定檔損毀保護**：`servers.json`、`user_settings.json` 與玩家設定檔無法解析時統一由 `SafeFileSystem.TryPreserveCorruptFile` 另存為 `.bad`；`server.properties` 讀寫與中繼資料定義統一使用 `PropertiesDocumentCodec`、`ServerPropertiesMetadata` 與 `ServerPropertiesValidator`。
- **`ServerManager`**：建立、刪除、更新、掃描；伺服器清單檔由 `ServerRegistryStore`、匯入由 `ServerImportWorkflow` 負責。首次存取時清理未完成的暫存目錄（失敗或取消後下次重試），未完成還原的快照則保留。同名或同目標之鍵控寫入／掃描／下載互斥鎖統一使用 `KeyedAsyncLock`；伺服器目錄一律經 `ServerSetupHelpers.ResolveServerDirectory`（單一路徑段且嚴格位於根目錄內）解析。
- **版本辨識**：`ServerInspector` 依 `version.json`、`MANIFEST.MF` 的 `Implementation-Version`／`Specification-Version` 與載入器函式庫目錄（`VersionNameComparer` 取最新）判斷；版本號正規化與相容語意（含 NeoForge／Fabric 推導）統一使用 `MinecraftVersionSemantics`；辨識不出時匯入失敗、掃描略過，不寫死預設版本。
- **匯入**：已有同名非空資料夾時拒絕；遷移模式在全部成功後才移除來源。來源為磁碟根目錄、存放根目錄或其上層時拒絕。

### 4. 執行階段與監控

- **多伺服器**：每台一個 `IServerRuntime`，由 `IServerRuntimeHost` 管理。
- **就緒偵測**：輸出不分大小寫含 `"Done ("` 或 `"Done in "` 即設 `IsReady` 並觸發 `ServerReady`。
- **啟動前檢查（`ServerStartPreflight`）**：連接埠衝突與啟動前自動備份。
- **平順停止（`ServerStopCoordinator`）**：送 `stop` 後等待 `ServerDefaults.GracefulStopTimeout`，逾時由使用者決定；`StopAllForShutdownAsync` 供關閉程式與自動更新共用，逐台處理並等待全部停止。
- **遺留行程（`RunningServerRegistry`）**：以 PID 與啟動時間登記，下次啟動時偵測並可終止。
- **記錄管線**：`LogLineBuffer` 由 UI 計時器批次排出至 `BulkObservableCollection<string>`（`AppendAndTrim` 超量時單次 Reset）；`ServerLogReader` 讀 `logs/latest.log` 尾端。監控與初始化視窗的主控台共用 `ConsoleLogListViewStyle`（虛擬化 `ListView`，項目範本在 `Resources/ConsoleLogResources.xaml`）與 `LogListAutoScroller`（新增後於版面配置完成時捲到底）。
- **啟動腳本（`StartScriptWriter`）**：`start_server.bat` 與 `user_jvm_args.txt` 只由此寫入；Java 一律用絕對路徑。
- **JVM 參數**：`JvmOptionPolicy.IsRejectedCustomArgument` 為唯一判斷，拒絕可執行外部命令的選項（含 `@argfile`、`-XX:VMOptionsFile=`、`-XX:OptionsFile`、`-XX:Flags=`、`-javaagent:`、`-Xrun`；未閉合引號視為無效）與批次檔特殊字元（`ScriptUnsafeChars`）。ViewModel、`ServerManager.UpdateServerAsync`（寫入清單前）、`StartScriptWriter` 與 `ServerLaunchPlanner` 皆依此檢查；更新後 `StartScriptWriter.UpdateUserJvmArgs`／`UpdateScriptJvmArgs`（經 `MemoryHelpers.TryReplaceScriptJvmArgs`）同步腳本。
- **行程結束**：`WaitForExitAsync` 的等待者共用同一個結束工作；伺服器自行結束時由 `ServerRuntime` 釋放資源。
- **Java 版本**：只依 Mojang 官方 JSON（`javaVersion.majorVersion`／`java_version.major`）取得或快取，未標註的舊版為 Java 8。

### 5. 模組管理

- **掃描**：平行讀取 `mods` 目錄並計算雜湊；以世代編號捨棄過期結果，同目錄掃描以 `KeyedAsyncLock` 序列化，單一檔案失敗只略過該檔。描述檔順序為 `fabric.mod.json`、`quilt.mod.json`、`neoforge.mods.toml`、`mods.toml`、`mcmod.info`；`ForgeTomlReader` 略過註解行且只認行首表頭。
- **相依解析（`ModDependencyPlanner`）**：只計入啟用中模組；雜湊相同或本機版本較新時不降級但仍展開子相依；找不到相容版本即不列入；Quilt 改查 Fabric、NeoForge 1.20.1 改查 Forge。
- **Modrinth（`ModrinthClient`）**：JSON 一律經 `JsonElementReader` 依型別讀取，單筆格式異常只略過該筆；`not_found` 以外的失敗記錄警告，HTTP 429 另行標示。`IHttpPort.PostJsonAsync` 直接回傳 `JsonDocument`。載入器查詢識別字轉換統一使用 `ModHelpers.ToModrinthLoaderId`，標準雜湊演算法名稱常數統一使用 `HashAlgorithmNames`（`Sha1`／`Sha256`／`Sha512`）。
- **`FlexVersion`**：移植自 Prism Launcher（GPL-3.0-only，見 `COPYING.md`）。
- **下載來源**：必須是官方 Modrinth CDN 且有雜湊值；官方來源判斷（含 `GitHubReleaseTrustPolicy`、`MojangVersionCatalog`、`LoaderInstallerService`）統一使用 `TrustedHostPolicy`（HTTPS、預設埠、無使用者資訊、主機白名單）。
- **檔案異動**：刪除與啟停同時處理 `.jar`／`.jar.disabled` 兩種變體並限定在 `mods` 目錄內；本機匯入先寫暫存檔再原子替換。
- **匯出（`ModListExporter`）**：TXT 以 `[啟用]`／`[停用]` 標示狀態，HTML 以純文字搭配語意 CSS 標籤呈現（不含 emoji）並與 XLSX 共用欄位標題；JSON 不寫 BOM；XLSX 每欄經 `SanitizeSpreadsheetFormula`。
- **下載（`HttpDownloadClient`）**：逾時為閒置逾時；無雜湊也無 ETag 時不續傳。
- **版本清單**：抓取失敗或為空時改用過期快取。
- **載入器安裝器（`LoaderInstallerService`）**：Fabric／Quilt 動態查詢官方 Meta（記憶體快取 1 小時），驗證官方網域並驗證雜湊（Quilt 優先 Meta `hashes`，其餘取 Maven `.sha256`／`.sha1`），取不到即拒絕；Meta 失敗時改用本機已驗證最新快取，下載驗證後自動清理舊檔（Fabric／Quilt 留最新 1 份，Forge／NeoForge 留最近 5 份）。大量檔案備份與安裝輸出之進度節流與區間換算統一使用 `ProgressThrottle`（搭配 `TimeProvider`）與 `ProgressMapping`。

### 6. 視窗與主題

- **對話框與大型視窗**：`ContentDialog` 經 `DialogStackCoordinator` 排隊（禁止按鈕事件內巢狀開啟；可讓位給巢狀對話框者實作 `INestableContentDialog`）；大型視窗為獨立 WinUI 視窗（`*Window`），ViewModel 繼承 `DialogViewModelBase`（具未儲存變更確認者另實作 `IUnsavedChangesPrompt`），視窗標題、尺寸、關閉結果、未儲存變更關閉確認與排序退訂統一由 `ModalWindowHost.AttachDialog`（含單純關閉多載 `ConfigureDialogWindow`／`BindRequestClose`）處理，命令內關閉用 `CloseDeferred`，一次性延遲初始化統一使用 `ModalWindowHost.RunOnLoadedOnce`（入口與規範見 A7、A14、A16、A40）。
- **導覽與表格**：主視窗用 `NavigationView`（匯入與開啟資料夾為動作項目，不改變選取）。表格採虛擬化 `ListView`（`TableListViewStyle`）、`TableFrame`（內建 `ShowCard` 卡片外框與 `VisualTreeHelperExtensions` 視覺樹走訪）、`TableCell`、`SortableTableHeader`（排序與欄寬見 A25）；各表格以 `TableFrame.SortTarget` 指定 `TableSortTarget<T>` 排序對象（記住排序並於重整／篩選後自動重套，可 `Detach()`／`Dispose()` 退訂）；表頭點選排序，僅分隔線按兩下自動對齊（以實際量測文字寬度計算），Alt+←／→ 調欄寬；最後一欄設 `ShowSplitter="False"` 與 `TableCell.ShowRightBorder="False"`。空狀態由 `TableFrame.IsEmpty`／`EmptyText` 以 `x:Load` 延遲建立，條件用 `UiBindHelpers.IsIdleEmpty`（忙碌中不顯示）或 `IsLoadedEmpty`（載入完成才顯示）。`x:Bind` 靜態路徑最後更新；與雙向 `SelectedItem` 同用的 `ItemsSource` 須為執行個體路徑。
- **鍵盤與無障礙**：重新整理按鈕掛 F5、頁面刪除鈕以 `ScopeOwner` 限定清單掛 Delete；清單列互動與外部點擊清除選取統一用 `ListViewBehaviors`（`ClearOnOutsidePress`、`SelectOnRightTap`、`InvokeCommand`：Enter／按兩下清單列，`DeleteCommand`：Delete），文字框用 `TextBoxShortcuts`（`FocusOnCtrlF`、`EnterCommand`），不在 Code-behind 重複處理按鍵。清單、無標籤輸入框、進度列與列內核取方塊設 `AutomationProperties.Name`，狀態文字設 `LiveSetting`，裝飾性 `FontIcon` 設 `AccessibilityView="Raw"`。
- **共用外觀與按鈕**：圖示加文字用 `IconLabel`、對話框圖示加訊息用 `IconMessageContent`、「標籤：值」用 `LabeledValue`、忙碌進度配狀態字用 `BusyStatusIndicator`，共用版面樣式置於 `App.xaml`。`PrimaryButtonStyle` 與 `DangerButtonStyle` 共用 `SolidButtonTemplate`，指標暫留／按下以透明度回饋，停用改專用筆刷；紅色統一用於刪除、封鎖、停止與重設類操作；按鈕順序為主要、次要、取消。
- **視覺語彙與外觀**：採 Mica、系統標題列與主題資源／字階 token（見 A16、A32、A34、A35）。`AccentColorService` 更新 App 專用鍵（`AccentBrush`、`AccentTextBrush` 等）與 CheckBox、RadioButton、ToggleSwitch、HyperlinkButton 輕量樣式鍵（框架鍵僅主題與系統一致時生效），文字以 `EnsureTextContrast` 確保 4.5:1 對比，並先更新 Light 字典，避免查找落到 Default 筆刷。`WindowLayoutHelper.SetMinimumSizeDip` 設定最小尺寸、實體像素邊界查詢統一使用 `WindowLayoutHelper.GetBounds`（見 A30），對話視窗為預設尺寸 2/3；主控台固定 `RequestedTheme="Dark"` 與 `ConsoleFontFamily`。
- **通知、操作進度與當機診斷**：`IUiService.ShowNotification` 以 InfoBar 顯示資訊／成功／警告、對話框顯示錯誤；開啟網址或資料夾失敗統一用 `UiServiceExtensions.OpenUrlOrWarn`／`OpenFolderOrWarn` 警告，伺服器停止前置檢查使用 `UiServiceExtensions.EnsureServerStopped`，進度對話框轉接使用 `UiServiceExtensions.CreateProgress`。`CrashDiagnostics` 以 `session.marker` 偵測上次異常結束並記錄 UI 執行緒例外。
- **ViewModel 組裝**：頁面及其子 ViewModel（管理頁四個、模組頁四個共用 `ModsContext`）由 `PageViewModelFactory` 建立後注入；依當次選取或執行期參數建立的短命對話視窗 ViewModel 由擁有者 ViewModel 直接建立，持有取消權杖者須 `using` 處置。
- **UI 執行緒與取消**：UI 執行緒不做檔案 I/O；設定寫入於 UI 執行緒擷取快照後以 `Task.Run` 寫檔（`SettingsManager` 以鎖序列化），偏好設定防抖寫入，關閉時 `MainViewModel.DisposePagesAsync` 先寫入未儲存變更。被 await 的方法以 `catch (Exception ex) when (ex is not OperationCanceledException)` 讓取消向上傳遞；最上層事件處理與射後不理流程另以 `catch (OperationCanceledException)` 記錄資訊。命令以 `CanExecute` 防重入（如 `IsSaving`、`IsOperating`），確認對話框後重新檢查伺服器狀態並使用確認前擷取的選取快照。

### 7. 名單管理

- `ServerPlayerConfigStore` 讀寫 `ops.json`、`whitelist.json`、`banned-players.json`、`banned-ips.json`。
- 讀取 `usercache.json` 提供名稱與 UUID 補完。

### 8. Java 偵測

- **Oracle Shim 去重**：過濾 `javapath` 轉接目錄與 shim 執行檔。
- **位元數**：`PortableExecutableInspector` 讀 PE 標頭判斷。
- **快取（`java_candidates_cache.json`）**：檔案未變動時不重新執行 `java -version`；變動項目重測後回寫。偵測以世代編號區分，只有最新一輪可寫入快取。

### 9. 單檔自包含發布

`scripts/dotnet_publish.ps1` 產出 `MinecraftServerManager.exe`。發布屬性與排除清單定義於 `App.csproj`（`PruneUnusedSingleFilePayload`），不用第三方加殼。`_UnusedPayload` 只列實測從未載入的檔案；升級 Windows App SDK 後須比對酬載並重新驗證。

啟動時清除 `%TEMP%\.net\MinecraftServerManager\` 下非目前執行個體的舊解壓資料夾。

### 10. 建置工具鏈

- **原始碼組織**：大型類別依職責拆為 `<類別>.<職責>.cs` partial 檔；不相依實例狀態的邏輯抽成獨立類別（如 `ShellLauncher`、`ConsoleCommandHistory`、`ServerPlayerLogParser`、`LocalModRowMapper`、`ServerStatusFormatter`、`PlayerTimeFormatter`）。
- **`scripts/lib/Common.ps1`**：腳本共用函式（版本與 CHANGELOG 章節解析、雜湊檔產生與驗證、重試、標籤同步與比對、Release 資產清單）；腳本與 workflow 不得重複實作。
- **`scripts/dotnet_quality_gate.ps1`**：編碼、版本（含 `CHANGELOG.md` 章節與 `docs/index.html` 的 `data-app-version` 標記，不一致即失敗）、Gitleaks（本機未安裝即失敗，CI 由 Action 負責）、還原（全面強制 `--locked-mode`）、格式（CI 驗證、本機自動修復）、Release 建置、測試（靜態屬性下限與預先列舉展開數量交叉驗證）與涵蓋率門檻（行 ≥ 80%、分支 ≥ 70%）。
- **`scripts/dotnet_publish.ps1`**：Release 單檔發布並顯示 SHA-256；`-SmokeTest` 加跑啟動煙霧測試。
- **`scripts/extract_release_notes.ps1`**：擷取 `CHANGELOG.md` 的目前版本章節，找不到或空白即失敗。
- **測試**：共用替身集中於 `tests/.../TestSupport`（`TestWait` 條件等待、`TestZip`、`TempDirectory`、`TestDependencies`、`NoOpUiService`／`ManualUiService`、`StubHttpPort`、`FakeServerRuntime`；偏好設定經 `UpdatePreferences` 走正式 `SetPreferences` 路徑，`src` 不留測試專用成員）；殼層啟動（`ShellLauncher`）與時鐘（`HttpDownloadClient`、`LoaderCatalogService`、`LoaderInstallerService`、`ServerBackupService`、`ServerDirectorySizeService`、`ProgressThrottle` 的 `TimeProvider`）經建構子注入；非同步呼叫一律傳 `TestContext.Current.CancellationToken`（xUnit1051 視為錯誤）；測試方法命名為 `方法_情境_結果`；組合根的安全設定（停用系統 Proxy、`ConnectCallback`）由 `CompositionRootConfigurationTests` 以原始碼驗證，不列入第 11 節規則表。
- **CI**：`ci-test.yml`、`codeql.yml`（C#、Actions、JavaScript）、`oss-scorecard.yml`、`validate-renovate.yml`；問題回報範本位於 `.github/ISSUE_TEMPLATE/`。
- **發布（`build-release.yml`）**：僅限 `master` 手動觸發，須同一 commit 的 CI 與 CodeQL 成功；建立標籤前重新確認標籤未指向其他 commit；資產含 `.exe`、SLSA 證明、SBOM 與 `.sha256`（SBOM 產生後才寫雜湊檔）；先建草稿，驗證後公開。
- **自動更新信任邊界**：`GitHubReleaseTrustPolicy` 供更新檢查與下載共用，只接受本專案 GitHub Release 的 HTTPS 資產（github.com、預設埠、無使用者資訊），Release 頁連結不符時改用預設頁。下載後驗證 SHA-256 與 x64 非 DLL 執行檔；套用時先複製為同目錄 `.new` 再交換，替換或啟動失敗即以 `.old` 還原，`.old` 於背景預熱清理。`.sha256` 與 `.exe` 同源，只能確認下載完整；Release 啟用不可變發布，發布後資產與 tag 無法替換，且擁有者與協作者帳號皆啟用雙重驗證。程式內不驗證簽章或 SLSA 證明（執行檔未做 Authenticode 簽章），需要時以 `gh attestation verify` 手動驗證。
- **Renovate**：.NET 與 Windows App SDK 不跨 major，新版本滿 3 天才建 PR，並每週維護鎖定檔；`global.json` SDK 與 Windows SDK 投影套件併入 .NET 群組，SBOM Tool、Gitleaks、Renovate 版本由自訂規則追蹤。

### 11. 共用入口與架構規則（A1～A45）

`SharedEntryArchitectureTests.cs` 以原始碼掃描強制執行下表。標「字串」者連字串內容一併掃描；XAML 只剝除 XML 註解，C# 插值運算式內的程式碼照常掃描，易跨行規則以全文比對。每條規則附違規樣本驗證正規式；白名單只列明確檔案，且每個檔案須實際命中該規則（未命中即應移除）；每個掃描範圍至少須有一個檔案。原始碼掃描排除專案層 `bin/`、`obj/` 與檔頭標示 `auto-generated` 的 `.g.cs`。新增入口或例外須同步更新本表與測試白名單。路徑省略 `src/MinecraftServerManager.` 前綴。

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

- `LoaderLayout`（Domain）：載入器檔案配置（啟動 JAR 前綴、函式庫路徑、安裝器排除）。
- `ServerDefaults`（Domain）：伺服器標準檔名與目錄名稱常數。
- `LoaderCompatibility`（Core）：載入器與模組支援載入器之相容性判斷。
- `LoaderKinds`（Domain）：`TryParse`、`ParseOrDefault`，以及 Modrinth 識別字對映 `ToModrinthId`／`TryParseModrinthId`。
- `SafeFileSystem.RetryOnTransientIo`（Infrastructure）：暫時性 I/O 重試。
- `SingleFlight<TKey, TValue>`（Infrastructure）：同鍵併發共用單一非同步結果。
- `NumericSegmentComparer`（Domain）：數字段版本比較。
- `ServerLaunchPlanner.BuildJvmAndTargetArgs`（Infrastructure）：`start_server.bat` 與程式內直接啟動共用 JVM 參數（UTF-8 輸出、建議 GC）與目標引數。
- `EphemeralStagingScope`（Infrastructure）：建立與匯入伺服器共用的暫存提交生命週期與失敗自動回滾。
- `DialogViewModelBase`、`IDialogCloseRequester`、`IUnsavedChangesPrompt`、`INestableContentDialog`、`ModalWindowHost.AttachDialog`／`BindRequestClose`（App）：對話框關閉、巢狀讓位與未儲存提示統一宿主。
- `ListViewBehaviors`、`VisualTreeHelperExtensions`、`BusyStatusIndicator`（App/Controls）：清單列互動與選取清除、視覺樹走訪與忙碌狀態指示。
- `PageKeys`（App/ViewModels）：頁面鍵常數。
- `ProcessControlExceptions.IsExpected`（App/Services）：行程控制預期例外判定。
- `UiServiceExtensions.OpenFileOrWarn`／`ShowInFolderOrWarn`（App/Services）：外部開啟失敗時警告。
- `ThemeBrush`（App/Controls）：主題筆刷解析。
