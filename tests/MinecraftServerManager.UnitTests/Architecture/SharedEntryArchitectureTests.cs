using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace MinecraftServerManager.UnitTests.Architecture;
/// <summary>架構規則測試（A1～A45），對應技術手冊第 11 節</summary>
public sealed partial class SharedEntryArchitectureTests
{
    #region 輔助方法

    private static void AssertNoViolations(List<SourceViolation> violations, string ruleId)
    {
        if (violations.Count == 0)
        {
            return;
        }

        string details = string.Join(
            Environment.NewLine,
            violations.Select(v => $"  - [{v.RuleId}] {v.FilePath}:{v.LineNumber} -> {v.LineContent}"));

        Assert.Fail($"架構規則 [{ruleId}] 檢查失敗，共發現 {violations.Count} 處違規呼叫：{Environment.NewLine}{details}");
    }

    private static List<string> GetCsprojIncludes(string csprojPath, string elementName)
    {
        if (!File.Exists(csprojPath))
        {
            throw new FileNotFoundException($"找不到專案檔：{csprojPath}");
        }

        var doc = XDocument.Load(csprojPath);
        return [.. doc.Descendants(elementName)
            .Select(x => (string?)x.Attribute("Include") ?? string.Empty)
            .Where(x => !string.IsNullOrWhiteSpace(x))];
    }

    #endregion

    #region 規則表（A1～A45，A9 另以專案參照檢查）

    private const string Infra = "src/MinecraftServerManager.Infrastructure/";
    private const string Core = "src/MinecraftServerManager.Core/";
    private const string Domain = "src/MinecraftServerManager.Domain/";
    private const string App = "src/MinecraftServerManager.App/";

    private static readonly string[] Src = ["src"];
    private static readonly string[] CSharp = ["*.cs"];
    private static readonly string[] Xaml = ["*.xaml"];
    private static readonly string[] XamlAndCSharp = ["*.xaml", "*.cs"];

    /// <summary>架構規則：範圍、違規正規式、說明、白名單（明確檔案）、違規樣本、是否保留字串、掃描樣式與是否跨行比對</summary>
    private sealed record Rule(
        string Id,
        string[] Scopes,
        Regex Pattern,
        string Message,
        string[] Allowed,
        string Sample,
        bool PreserveStrings = false,
        string[]? FilePatterns = null,
        bool Multiline = false)
    {
        public string[] Patterns => FilePatterns ?? CSharp;

        public bool IsAllowed(string path) => Allowed.Contains(path, StringComparer.OrdinalIgnoreCase);

        public IEnumerable<(string RelativePath, string FullPath)> Files =>
            Scopes.SelectMany(scope => Patterns.SelectMany(pattern => SourceScanner.GetSourceFiles(scope, pattern)));

        public List<SourceViolation> Scan(IEnumerable<(string RelativePath, string FullPath)> files, Func<string, bool> isAllowed) =>
            SourceScanner.ScanViolations(files, Pattern, Id, Message, isAllowed, PreserveStrings, Multiline);
    }

    /// <summary>規則表</summary>
    private static readonly Dictionary<string, Rule> Rules = new Rule[]
    {
        new("A1", Src, A1Regex(), "檔案系統 I/O 必須統一透過 SafeFileSystem 或 AtomicFileWriter",
            [Infra + "FileSystem/SafeFileSystem.cs", Infra + "FileSystem/SafeFileSystem.Enumeration.cs", Infra + "FileSystem/SafeFileSystem.IO.cs",
                Infra + "FileSystem/SafeFileSystem.Operations.cs", Infra + "FileSystem/SafeFileSystem.PathPolicy.cs",
                Infra + "FileSystem/SafeZipArchive.cs", Infra + "FileSystem/SafeZipArchive.BoundedZipWriter.cs", Infra + "Utilities/AtomicFileWriter.cs",
                Infra + "Logging/RotatingFileLoggerProvider.cs", Infra + "Http/HttpDownloadClient.Download.cs",
                Infra + "Utilities/OpenXmlSpreadsheetBuilder.cs", // 記憶體 ZIP 寫入，不涉及檔案系統
                Infra + "Servers/ServerInspector.Memory.cs", // SafeFileSystem.OpenRead 串流外包 StreamReader 逐行解析
                Infra + "Servers/ServerInspector.VersionDetection.cs"], // 同上（讀取記錄檔尾段）
            "var text = File.ReadAllText(path);\nvar reader = new StreamReader(path);\nvar text2 = IO.File.ReadAllText(path);\nusing static System.IO.Path;"),

        new("A2", Src, A2Regex(), "壓縮檔操作與單一項目讀取必須透過 SafeZipArchive（OpenXmlSpreadsheetBuilder 僅限記憶體建構例外）",
            [Infra + "FileSystem/SafeZipArchive.cs", Infra + "FileSystem/SafeZipArchive.BoundedZipWriter.cs", Infra + "Utilities/OpenXmlSpreadsheetBuilder.cs"],
            "archive.ExtractToDirectory(target);", Multiline: true),

        new("A3", Src, A3Regex(), "外部行程管理必須統一由 ProcessRunner 負責",
            [Infra + "Process/ProcessRunner.cs", Infra + "Process/ShellLauncher.cs"],
            "var all = Process.GetProcessesByName(name);\nprivate readonly Process _p = new();", Multiline: true),

        new("A4", Src, A4Regex(), "HttpClient 與處理常式僅得於 AppCompositionRoot 集中建立",
            [App + "AppCompositionRoot.cs"],
            "var client = new HttpClient();\nHttpClient c = new();", Multiline: true),

        new("A5", Src, A5Regex(), "JSON 解析與序列化必須透過 JsonCodec 與 JsonElementReader",
            [Infra + "Utilities/JsonCodec.cs", Infra + "Utilities/JsonElementReader.cs"],
            "var model = JsonSerializer.Deserialize<Model>(json);\nvar node = JsonNode.Parse(text);\nvar m = serializer.Deserialize<Model>(json);\nvar r = response.Content.ReadFromJsonAsync<Model>();"),

        new("A6", Src, A6Regex(), "正規表示式一律使用 [GeneratedRegex]，禁止執行期動態建構或靜態方法呼叫", [],
            "var regex = new\n    Regex(pattern);\nRegex r = new(pattern);", Multiline: true),

        new("A7", Src, A7Regex(), "UI 派送、檔案選取器、對話方塊、訊息框與計時器必須由 IUiService (WinUiService) 統一管理；ViewModel 禁用 DispatcherQueue",
            [App + "Services/WinUiService.cs", App + "Services/WinUiService.CoalescingProgress.cs", App + "Services/WinUiService.WinUiTimer.cs", App + "App.xaml.cs", App + "MainWindow.xaml.cs", App + "MainWindow.Notifications.cs", App + "Controls/TableSortExtensions.cs"],
            "DispatcherQueue.TryEnqueue(Refresh);"),

        new("A8", ["src", "tests"], A8Regex(), "專案全境嚴格禁止 unsafe 程式碼", [],
            "unsafe { }"),

        new("A10", [App + "ViewModels"], A10Regex(), "ViewModel 嚴禁持有原生 Process 實體", [],
            "private readonly List<Process> _processes = [];"),

        new("A11", Src, A11Regex(), "檔案與資料雜湊計算必須統一經由 HashCalculator（HttpDownloadClient 僅限續傳下載串流例外）",
            [Infra + "Utilities/HashCalculator.cs", Infra + "Http/HttpDownloadClient.Download.cs"],
            "byte[] hash = SHA256.HashData(bytes);"),

        new("A12", Src, A12Regex(), "記錄輸出必須統一由 AppLogging 與 ComponentLogger 管理，禁止直呼 Console、Trace 或 Debug 輸出", [],
            "Console.Error.WriteLine(message);"),

        new("A13", [App + "ViewModels"], A13Regex(), "ViewModel 內禁止出現裸 _ = XxxAsync(，必須經由 ViewModelBase.RunSafeAsync 統一處理例外與記錄", [],
            "_ = _service.LoadAsync<Item>(token);", Multiline: true),

        new("A14", Src, A14Regex(), "系統提示音效必須統一由 AudioFeedback 提供",
            [App + "Services/AudioFeedback.cs"],
            "SystemSounds.Beep.Play();"),

        new("A15", Src, A15Regex(), "全專案嚴格禁止使用 Debug 或 Trace 等級輸出日誌（一般使用 Information，非致命例外使用 Warning，嚴重錯誤使用 Error）", [],
            "_logger.LogDebug(message);"),

        new("A16", Src, A16Regex(), "視窗標題列、系統強調色、模態視窗繫結與圖示資源載入必須統一由專屬服務管理",
            [App + "Services/WindowChromeService.cs", App + "Services/AccentColorService.cs"],
            "window.AppWindow.TitleBar.ButtonForegroundColor = color;"),

        new("A17", Src, A17Regex(), "Windows 保留裝置名稱檢查必須統一使用 ServerName.IsWindowsDeviceName，模組檔名與雜湊挑選必須統一使用 ModHelpers",
            [Domain + "ValueObjects/ServerName.cs", Core + "Mods/ModHelpers.cs"],
            "bool reserved = name is \"CON\" or \"NUL\";", PreserveStrings: true),

        new("A18", Src, A18Regex(), "例外攔截必須指定型別與變數（或重拋），不得無型別 catch 或吞沒 catch (Exception)",
            [Infra + "Logging/RotatingFileLoggerProvider.cs", Infra + "Logging/CrashDiagnostics.cs"],
            "try { Run(); } catch (Exception) { Log(); }", Multiline: true),

        new("A19", Src, A19Regex(), "模組檔案副檔名判斷必須統一使用 ModHelpers（Domain 層 OnlineModVersion 因相依方向例外）",
            [Core + "Mods/ModHelpers.cs", Domain + "Mods/OnlineModVersion.cs"],
            "bool jar = name.EndsWith(\".jar\", StringComparison.OrdinalIgnoreCase);", PreserveStrings: true),

        new("A20", Src, A20Regex(), "版本快取檔名、Mojang Manifest 與 PaperMC API 端點必須統一由 MojangVersionCatalog 提供",
            [Infra + "Loaders/MojangVersionCatalog.cs"],
            "const string Url = \"https://piston-meta.mojang.com/mc/game/version_manifest_v2.json\";", PreserveStrings: true),

        new("A21", Src, A21Regex(), "原生 Win32 互通宣告必須集中於 App.xaml.cs、AudioFeedback、ModalWindowHost、WindowIconHelper、WindowLayoutHelper",
            [App + "App.xaml.cs", App + "Services/AudioFeedback.cs", App + "Services/ModalWindowHost.cs", App + "Services/WindowIconHelper.cs", App + "Services/WindowLayoutHelper.cs"],
            "private static extern int GetDpiForWindow(nint hwnd);"),

        new("A22", Src, A22Regex(), "系統資料夾路徑查詢必須統一使用 RuntimePaths",
            [Infra + "Utilities/RuntimePaths.cs"],
            "string temp = Path.GetTempPath();"),

        new("A23", Src, A23Regex(), "必須使用 Path.IsPathFullyQualified 與 Path.TrimEndingDirectorySeparator（SafeZipArchive 拒絕任何具根路徑之壓縮項目為例外）",
            [Infra + "FileSystem/SafeZipArchive.MemberValidation.cs"],
            "bool rooted = Path.IsPathRooted(path);"),

        new("A24", Src, A24Regex(), "進度轉接、換算與節流必須使用 SynchronousProgress<T>、ProgressMapping 與 ProgressThrottle，禁止 new Progress<T>", [],
            "var progress = new Progress<int>(Report);\nProgress<int> p = new(Report);", Multiline: true),

        new("A25", Src, A25Regex(), "表格排序必須統一使用 TableSortExtensions.SortBy",
            [App + "Controls/TableSortExtensions.cs"],
            "var comparer = new SortKeyComparer();", Multiline: true),

        new("A26", Src, A26Regex(), "暫存檔命名必須統一使用 AtomicFileWriter.CreateTempSiblingPath",
            [Infra + "Utilities/AtomicFileWriter.cs"],
            "string temp = path + \".tmp\";", PreserveStrings: true),

        new("A27", Src, A27Regex(), "ANSI 清洗必須使用 ModHelpers.StripColorAndFormattingCodes，記憶體參數解析必須使用 MemoryHelpers",
            [Core + "Mods/ModHelpers.cs", Core + "Utilities/MemoryHelpers.cs"],
            "[GeneratedRegex(@\"\\e\\[[0-9;]*m\")]", PreserveStrings: true, Multiline: true),

        new("A28", Src, A28Regex(), "LoaderKind 解析必須統一使用 LoaderKinds",
            [],
            "Enum.TryParse(text, ignoreCase: true, out LoaderKind kind);", Multiline: true),

        new("A29", [App + "ViewModels", App + "Views", App + "Controls"], A29Regex(), "ViewModel、View 與控制項的檔案 I/O 必須經由 Core 連接埠注入，不得直接呼叫 Infrastructure 靜態工具", [],
            "string dir = RuntimePaths.GetUserDataDir();"),

        new("A30", Src, A30Regex(), "視窗尺寸調整必須統一使用 WindowLayoutHelper.ResizeToDip，避免實體像素與邏輯像素混用",
            [App + "Services/WindowLayoutHelper.cs"],
            "_appWindow.ResizeClient(size);"),

        new("A31", Src, A31Regex(), "PageServices 僅可出現在組合根與 PageViewModelFactory，ViewModel 不得持有整包服務",
            [App + "AppCompositionRoot.cs", App + "ViewModels/PageServices.cs", App + "ViewModels/PageViewModelFactory.cs"],
            "private readonly PageServices _services;"),

        new("A32", Src, A32Regex(), "視窗材質與標題列必須統一由 WindowChromeService 套用",
            [App + "Services/WindowChromeService.cs"],
            "SystemBackdrop = new MicaBackdrop();"),

        new("A33", Src, A33Regex(), "有狀態的基礎設施物件只能由組合根或其專屬擁有者建立",
            [App + "App.xaml.cs", App + "ViewModels/PageViewModelFactory.cs", Infra + "Servers/ServerManager.cs", Infra + "Servers/ServerRuntimeHost.cs", Infra + "Mods/LocalModScanner.cs"],
            "var runner = new Infrastructure.Process.ProcessRunner();\nServerRuntime rt = new();", Multiline: true),

        new("A34", [App.TrimEnd('/')], A34Regex(), "XAML 禁止寫死色碼與數值字級，必須使用主題資源與字階 token",
            [App + "App.xaml"],
            "<Setter Property=\"FontSize\" Value=\"14\" />\n<Border Background=\"#FFF\" />", PreserveStrings: true, FilePatterns: Xaml, Multiline: true),

        new("A35", Src, A35Regex(), "全專案原始碼與 XAML 禁止 emoji（保留 ➔），App 圖示字型必須使用 SymbolThemeFontFamily", [],
            "<FontIcon FontFamily=\"Segoe Fluent Icons\" />", PreserveStrings: true, FilePatterns: XamlAndCSharp),

        new("A36", Src, A36Regex(), "載入器檔案配置字串（server.jar、win_args.txt、run.bat、latest.log、crash-reports）僅限 ServerDefaults／LoaderLayout 定義",
            [Domain + "Servers/ServerDefaults.cs"], // 標準檔名常數之唯一定義處
            "var name = \"server.jar\";\nvar dir = \"crash-reports\";", PreserveStrings: true),

        new("A37", [Core, Infra], A37Regex(), "Core／Infrastructure 禁比對載入器名稱字面值（fabric、forge、neoforge、quilt、paper），須使用 LoaderKind／LoaderKinds／LoaderLayout",
            [Infra + "Servers/ServerInspector.cs"], // 啟動 JAR 檔名前綴偵測（"fabric" 為檔名前綴，非載入器判斷）
            "if (string.Equals(target, \"fabric\", StringComparison.OrdinalIgnoreCase)) { }\nif (name == \"paper\") { }", PreserveStrings: true),

        new("A38", Src, A38Regex(), "禁手寫 Thread.Sleep 重試迴圈，暫時性 I/O 重試必須走 SafeFileSystem.RetryOnTransientIo",
            [Infra + "FileSystem/SafeFileSystem.Operations.cs"], // RetryOnTransientIo 本體
            "for (int attempt = 1; ; attempt++) { Thread.Sleep(delay * attempt); }"),

        new("A39", [Infra], A39Regex(), "禁直接建立 Lazy<Task<…>> 單飛快取，須統一使用 SingleFlight<TKey, TValue>",
            [Infra + "Utilities/SingleFlight.cs"], // 單飛實作本體
            "private readonly ConcurrentDictionary<string, Lazy<Task<int>>> _cache = new();"),

        new("A40", [App + "Views"], A40Regex(), "對話框關閉必須經由 ModalWindowHost.BindRequestClose 繫結，禁止直接訂閱或取消訂閱 RequestClose",
            [],
            "viewModel.RequestClose += OnClose;"),

        new("A41", [App + "ViewModels"], A41Regex(), "ViewModel 禁直接呼叫 IExternalLauncher 的外部開啟方法，須經 UiServiceExtensions 的 *OrWarn 擴充方法",
            [],
            "_launcher.OpenUrl(url);"),

        new("A42", ["tests"], A42Regex(), "測試衛生：禁 Thread.Sleep（改用可觀察訊號）、無 handler 的 new HttpClient()、Process.Start（實際行程測試限白名單）",
            [
                "tests/MinecraftServerManager.UnitTests/TestSupport/TempDirectory.cs", // 清除暫存目錄時等待檔案釋放
                "tests/MinecraftServerManager.UnitTests/TestSupport/TestJunction.cs", // 建立 junction 需啟動 cmd.exe
            ],
            "Thread.Sleep(50);\nvar client = new HttpClient();\nProcess.Start(startInfo);"),

        new("A43", ["src", "tests"], A43Regex(), "禁止空 catch 區塊（含僅註解者），至少須記錄或重拋；日誌器自身失敗無回報管道者列白名單",
            [
                Infra + "Logging/RotatingFileLoggerProvider.cs", // 日誌器自身寫入、排清、輪替失敗，無其他回報管道
                Infra + "Logging/CrashDiagnostics.cs", // 崩潰記錄自身失敗，無其他回報管道
            ],
            "try { Run(); } catch { }", Multiline: true),

        new("A44", Src, A44Regex(), "攔截 OperationCanceledException 的區塊內須重拋、記錄（Logger／ComponentLogger／AppLogging）或經 UI 通知（_ui.／ui.／Notify／Show*），不得無聲結束",
            [
                // 單一位址逾時改試下一位址；全部位址失敗時迴圈結束後以 lastException 包裝重拋
                Infra + "Http/HttpUrlPolicy.cs",
                // RunOnUiAsync 將取消經 TrySetCanceled 傳回等待端，由等待端決定處理與記錄
                App + "Services/WinUiService.cs",
            ],
            "try { Run(); } catch (OperationCanceledException) { Log(); }", Multiline: true),

        new("A45", [App.TrimEnd('/')], A45Regex(), "XAML 繫結一律使用 x:Bind，禁止 {Binding}",
            [],
            "<TextBlock Text=\"{Binding Name}\" />", FilePatterns: Xaml),
    }.ToDictionary(static rule => rule.Id, StringComparer.Ordinal);

    /// <summary>所有以正規式掃描的規則代號</summary>
    public static TheoryData<string> RuleIds => [.. Rules.Keys];

    /// <summary>白名單檔案與其規則代號</summary>
    public static TheoryData<string, string> WhitelistEntries =>
        [.. Rules.Values.SelectMany(rule => rule.Allowed.Select(path => (rule.Id, path)))];

    #endregion

    #region 架構規則測試（A1～A45）

    [Theory]
    [MemberData(nameof(RuleIds))]
    public void Rule_SourceScan_HasNoViolations(string ruleId)
    {
        Rule rule = Rules[ruleId];
        foreach (string scope in rule.Scopes)
        {
            foreach (string pattern in rule.Patterns)
            {
                int count = SourceScanner.GetSourceFiles(scope, pattern).Count;
                Assert.True(count > 0, $"[{ruleId}] 掃描範圍無任何檔案（目錄是否改名？）：{scope} ({pattern})");
            }
        }

        AssertNoViolations(rule.Scan(rule.Files, rule.IsAllowed), rule.Id);
    }

    [Theory]
    [MemberData(nameof(RuleIds))]
    public void Rule_Sample_ShouldMatchPattern(string ruleId)
    {
        Rule rule = Rules[ruleId];
        string extension = rule.Sample.StartsWith('<') ? "sample.xaml" : "sample.cs";
        string cleaned = SourceScanner.Clean(extension, rule.Sample, rule.PreserveStrings);

        Assert.Matches(rule.Pattern, cleaned);
    }

    /// <summary>A44 反向樣本：區塊內重拋、記錄或 UI 通知者不得違規</summary>
    [Theory]
    [InlineData("try { Run(); } catch (OperationCanceledException) { throw; }")]
    [InlineData("try { Run(); } catch (TaskCanceledException) { throw; }")]
    [InlineData("try { Run(); } catch (System.OperationCanceledException) { throw; }")]
    [InlineData("try { Run(); } catch (OperationCanceledException) { Logger.Information(\"已取消\"); }")]
    [InlineData("try { Run(); } catch (OperationCanceledException) when (token.IsCancellationRequested) { _logger.Information(\"已取消\"); }")]
    [InlineData("try { Run(); } catch (OperationCanceledException) { _ui.Notify(\"已取消\", NotificationType.Info); }")]
    public void A44_Sample_HandledCancellation_ShouldNotMatch(string sample)
    {
        string cleaned = SourceScanner.Clean("sample.cs", sample, false);

        Assert.DoesNotMatch(Rules["A44"].Pattern, cleaned);
    }

    [Theory]
    [MemberData(nameof(WhitelistEntries))]
    public void Whitelist_Entry_ShouldExistAndHitRule(string ruleId, string relativePath)
    {
        Rule rule = Rules[ruleId];
        string fullPath = Path.Combine(SourceScanner.SolutionRoot, relativePath);

        Assert.True(File.Exists(fullPath), $"[{ruleId}] 白名單檔案不存在：{relativePath}");
        Assert.Contains(rule.Scopes, scope => relativePath.StartsWith(scope, StringComparison.OrdinalIgnoreCase));
        Assert.True(rule.Scan([(relativePath, fullPath)], static _ => false).Count > 0, $"[{ruleId}] 白名單檔案未命中規則，應移除：{relativePath}");
    }

    [Fact]
    public void RuleTable_TechnicalOverview_MatchesTestedRules()
    {
        string doc = File.ReadAllText(Path.Combine(SourceScanner.SolutionRoot, "docs", "TECHNICAL_OVERVIEW.md"));
        var documented = doc.Split('\n')
            .Where(line => line.StartsWith("| A", StringComparison.Ordinal))
            .Select(line => line.Split('|')[1].Trim())
            .Order(StringComparer.Ordinal);

        Assert.Equal(Rules.Keys.Append("A9").Order(StringComparer.Ordinal), documented);
    }

    /// <summary>Domain／Core 之 PackageReference 白名單（目前皆無套件參照）</summary>
    private static readonly string[] DomainPackageAllowlist = [];
    private static readonly string[] CorePackageAllowlist = [];

    /// <summary>A9-1：專案參照與套件白名單</summary>
    [Fact]
    public void A9_ProjectReferences_ShouldRespectArchitectureBoundaries()
    {
        string domainCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Domain", "MinecraftServerManager.Domain.csproj");
        string coreCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Core", "MinecraftServerManager.Core.csproj");
        string infraCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Infrastructure", "MinecraftServerManager.Infrastructure.csproj");

        var domainRefs = GetCsprojIncludes(domainCsproj, "ProjectReference");
        Assert.True(domainRefs.Count == 0, $"Domain 專案不得參照任何外部專案，目前參照：{string.Join(", ", domainRefs)}");

        var coreRefs = GetCsprojIncludes(coreCsproj, "ProjectReference");
        Assert.True(
            coreRefs.All(r => r.Contains("MinecraftServerManager.Domain", StringComparison.OrdinalIgnoreCase)),
            $"Core 專案僅得參照 Domain 專案，目前參照：{string.Join(", ", coreRefs)}");

        var infraRefs = GetCsprojIncludes(infraCsproj, "ProjectReference");
        Assert.False(
            infraRefs.Any(r => r.Contains("MinecraftServerManager.App", StringComparison.OrdinalIgnoreCase)),
            $"Infrastructure 專案不得逆向參照 App 專案，目前參照：{string.Join(", ", infraRefs)}");

        var domainPackages = GetCsprojIncludes(domainCsproj, "PackageReference");
        Assert.Empty(domainPackages.Except(DomainPackageAllowlist, StringComparer.OrdinalIgnoreCase));

        var corePackages = GetCsprojIncludes(coreCsproj, "PackageReference");
        Assert.Empty(corePackages.Except(CorePackageAllowlist, StringComparer.OrdinalIgnoreCase));
    }

    /// <summary>A9-2：Domain／Core 不得使用 System.IO、System.Net 或 System.Diagnostics 命名空間（含 global using 與完整限定名稱）</summary>
    [Fact]
    public void A9_Usings_ShouldNotImportIoNetOrDiagnostics()
    {
        var domainFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.Domain");
        Assert.NotEmpty(domainFiles);
        var domainViolations = SourceScanner.ScanViolations(
            domainFiles,
            A9DomainUsingRegex(),
            "A9",
            "Domain 核心領域層不得使用 System.IO、System.Net 或 System.Diagnostics（含 global using 與完整限定名稱）",
            _ => false);
        AssertNoViolations(domainViolations, "A9-Domain");

        var coreFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.Core");
        Assert.NotEmpty(coreFiles);
        var coreViolations = SourceScanner.ScanViolations(
            coreFiles,
            A9CoreUsingRegex(),
            "A9",
            "Core 業務核心層不得使用 System.IO、System.Net.Http 或 System.Diagnostics（含 global using 與完整限定名稱）",
            _ => false);
        AssertNoViolations(coreViolations, "A9-Core");
    }

    /// <summary>A9-3：驗證 A9 正規式可捕捉 global using 與完整限定名稱</summary>
    [Fact]
    public void A9_Regex_ShouldMatchGlobalAndQualifiedNames()
    {
        Assert.Matches(A9DomainUsingRegex(), "global using System.IO;");
        Assert.Matches(A9DomainUsingRegex(), "System.Net.Http.HttpClient");
        Assert.Matches(A9DomainUsingRegex(), "System.Diagnostics.Process");
        Assert.Matches(A9CoreUsingRegex(), "global using System.IO;");
        Assert.Matches(A9CoreUsingRegex(), "System.Net.Http.HttpClient");
        Assert.Matches(A9CoreUsingRegex(), "System.Diagnostics.Process");
    }

    #endregion

    #region 規則比對正規式（A1～A45）

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.|IO\.)?(File\.|Directory\.|FileInfo\b|DirectoryInfo\b|FileStream\b|DriveInfo\b))|(?<![\w\.])new\s+(System\.IO\.)?(StreamReader|StreamWriter|FileSystemWatcher)\s*\(|(?<![\w\.])using\s+static\s+System\.IO\.")]
    private static partial Regex A1Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.Compression\.)?(ZipFile\.|ZipFile\b)|new\s+(System\.IO\.Compression\.)?ZipArchive\b|\b\w*Entry\w*\.Open\(\))|\.(ExtractToDirectory|ExtractToFile|CreateEntryFromFile)\(")]
    private static partial Regex A2Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Diagnostics\.)?(Process\.(Start|GetProcessById|GetProcessesByName|GetProcesses)\b|ProcessStartInfo\b)|new\s+(System\.Diagnostics\.)?Process\s*\()|(?<![\w\.])(System\.Diagnostics\.)?Process\??\s+\w+\s*=\s*new\s*\(")]
    private static partial Regex A3Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.Net\.Http\.)?HttpClient\b|SocketsHttpHandler\b|HttpClientHandler\b|(System\.Net\.Http\.)?HttpClient\??\s+\w+\s*=\s*new\s*\()")]
    private static partial Regex A4Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Text\.Json\.)?(JsonSerializer\.|JsonDocument\.)|new\s+(System\.Text\.Json\.)?JsonSerializerOptions\b|(System\.Text\.Json\.)?JsonNode\.Parse\b)|(?<!JsonCodec)\.Deserialize<|\.(ReadFromJsonAsync|GetFromJsonAsync)\b|\.(GetString|GetInt32|GetInt64|GetBoolean)\(\)")]
    private static partial Regex A5Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.Text\.RegularExpressions\.)?Regex\s*\(|(System\.Text\.RegularExpressions\.)?Regex\.(IsMatch|Match|Matches|Replace|Split|Count|EnumerateMatches|EnumerateSplits)\s*\(|(System\.Text\.RegularExpressions\.)?Regex\??\s+\w+\s*=\s*new\s*\()")]
    private static partial Regex A6Regex();

    [GeneratedRegex(@"(?<![\w\.])(MessageBoxW\b|DispatcherTimer\b|DispatcherQueueTimer\b|FileOpenPicker\b|FileSavePicker\b|FolderPicker\b|new\s+ContentDialog\b|DispatcherQueue\b)|\.CreateTimer\(")]
    private static partial Regex A7Regex();

    [GeneratedRegex(@"(?<![\w\.])unsafe\b")]
    private static partial Regex A8Regex();

    [GeneratedRegex(@"(?<![\w\.])System\.(IO|Net|Diagnostics(?!\.CodeAnalysis))\b")]
    private static partial Regex A9DomainUsingRegex();

    [GeneratedRegex(@"(?<![\w\.])System\.(IO|Net\.Http|Diagnostics(?!\.CodeAnalysis))\b")]
    private static partial Regex A9CoreUsingRegex();

    [GeneratedRegex(@"(?<![\w\.])(System\.Diagnostics\.Process\b|Process(\?|\[\])?\s+[A-Za-z_])|<\s*Process\s*[,>]")]
    private static partial Regex A10Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Security\.Cryptography\.)?(SHA256\.|SHA1\.|MD5\.|SHA512\.|IncrementalHash\b|HashAlgorithm\.|HashAlgorithmName\.|CryptographicOperations\.HashData\b)|System\.Security\.Cryptography\.HashAlgorithm\b)")]
    private static partial Regex A11Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.)?Console\.((Error|Out)\.)?(WriteLine|Write)|(System\.Diagnostics\.)?(Trace|Debug)\.(WriteLine|Write|Print|TraceInformation|TraceWarning|TraceError)|(System\.Diagnostics\.)?Debugger\.Log)\(")]
    private static partial Regex A12Regex();

    [GeneratedRegex(@"(?<![\w\.])_\s*=\s*(?!(?:ViewModelBase\.)?RunSafeAsync\b)(?:([a-zA-Z_]\w*\.)*([a-zA-Z_]\w*Async)(<[^<>()]*>)?|Task\.Run)\(")]
    private static partial Regex A13Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Media\.)?(SystemSounds\b|SoundPlayer\b)|MessageBeep\b)")]
    private static partial Regex A14Regex();

    [GeneratedRegex(@"(?<![\w\.])(_?[Ll]ogger|Log)\.(Log)?(Debug|Trace)\(|\bLog\(\s*LogLevel\.(Debug|Trace)\b|\bLevel\s*=\s*LogLevel\.(Debug|Trace)\b")]
    private static partial Regex A15Regex();

    [GeneratedRegex(@"(?<![\w\.])(AppWindowTitleBar\b|UISettings\b|SetWindowLongPtrW\b|LoadIconW\b)|\.TitleBar\b")]
    private static partial Regex A16Regex();

    [GeneratedRegex(@"(""(CLOCK\$|PRN|CON|NUL|AUX|COM1|LPT1)""|(?<!ModHelpers\.)\bModFilenameStem\s*\(|(?<!ModHelpers\.)\bResolveHash\s*\(\s*ModFile)")]
    private static partial Regex A17Regex();

    [GeneratedRegex(@"(?<![\w\.])catch\s*(\{|$|\(\s*(System\.)?Exception\s*\)\s*\{(?!(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\bthrow\s*;))")]
    private static partial Regex A18Regex();

    [GeneratedRegex(@"EndsWith\(\s*""\.jar|\.jar\.disabled""")]
    private static partial Regex A19Regex();

    [GeneratedRegex(@"mc_versions_cache\.json|piston-meta\.mojang\.com|fill\.papermc\.io")]
    private static partial Regex A20Regex();

    [GeneratedRegex(@"\[\s*(LibraryImport|DllImport)\b|\bstatic\s+extern\s")]
    private static partial Regex A21Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.)?Environment\.GetFolderPath|(System\.IO\.)?Path\.GetTempPath)\b")]
    private static partial Regex A22Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.)?Path\.IsPathRooted\(|\.TrimEnd\(\s*(System\.IO\.)?Path\.(Alt)?DirectorySeparatorChar)")]
    private static partial Regex A23Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.)?Progress\s*<|(System\.)?Progress\s*<[^;=]*>\??\s+\w+\s*=\s*new\s*\()")]
    private static partial Regex A24Regex();

    [GeneratedRegex(@"(?<![\w\.])new\s+SortKeyComparer\b|\bSortKeyComparer\s*\.\s*Instance\b")]
    private static partial Regex A25Regex();

    [GeneratedRegex(@"\.tmp""")]
    private static partial Regex A26Regex();

    [GeneratedRegex(@"GeneratedRegex\([^)]*(\\x1[bB]|\\u001[bB]|\\e|-Xm[xs]|Xmx\|Xms)")]
    private static partial Regex A27Regex();

    [GeneratedRegex(@"Enum\s*\.\s*(TryParse|Parse)\s*(<\s*LoaderKind\s*>|\([^;]*(typeof\s*\(\s*LoaderKind\s*\)|\bout\s+LoaderKind\b))")]
    private static partial Regex A28Regex();

    [GeneratedRegex(@"(?<![\w\.])(SafeFileSystem|ModFileInstaller|ServersRootRelocator|PropertiesDocumentCodec|AtomicFileWriter|SafeZipArchive|RuntimePaths|StartScriptWriter|ServerTombstoneManager)\.")]
    private static partial Regex A29Regex();

    [GeneratedRegex(@"(?i:\b_?\w*appwindow)\.(Resize|ResizeClient)\(")]
    private static partial Regex A30Regex();

    [GeneratedRegex(@"\bPageServices\b")]
    private static partial Regex A31Regex();

    [GeneratedRegex(@"\b(SystemBackdrop|MicaBackdrop|ExtendsContentIntoTitleBar)\b|\bSetTitleBar\(")]
    private static partial Regex A32Regex();

    [GeneratedRegex(@"\bnew\s+(?:\w+\s*\.\s*)*(ServerRegistryStore|ServerImportWorkflow|ModIndexPersistence|ServerRuntime|ServerInitializationWorkflow|SettingsManager|ProcessRunner)\s*\(|\b(?:\w+\s*\.\s*)*(ServerRegistryStore|ServerImportWorkflow|ModIndexPersistence|ServerRuntime|ServerInitializationWorkflow|SettingsManager|ProcessRunner)\??\s+\w+\s*=\s*new\s*\(")]
    private static partial Regex A33Regex();

    [GeneratedRegex(@"#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3,4})\b|\bFontSize=""\d|Property=""FontSize""\s+Value=""\d")]
    private static partial Regex A34Regex();

    [GeneratedRegex(@"[\uD83C-\uD83E][\uDC00-\uDFFF]|(?!\u2794)[\u2600-\u27BF\u2B00-\u2BFF]|\uFE0F|\bFontFamily=""Segoe|FontFamily\(\s*""Segoe")]
    private static partial Regex A35Regex();

    [GeneratedRegex(@"(?<![\w\.])(""(server\.jar|win_args\.txt|run\.bat|latest\.log|crash-reports)"")")]
    private static partial Regex A36Regex();

    [GeneratedRegex(@"(?i)(\bEquals\s*\([^;]*?|\bStartsWith\s*\(\s*|\bEndsWith\s*\(\s*|==\s*|!=\s*|\bcase\s+|\bis\s+)""(fabric|forge|neoforge|quilt|paper)""|""(fabric|forge|neoforge|quilt|paper)""\s*(==|!=)")]
    private static partial Regex A37Regex();

    [GeneratedRegex(@"\bThread\.Sleep\s*\(")]
    private static partial Regex A38Regex();

    [GeneratedRegex(@"\bLazy\s*<\s*Task\s*<")]
    private static partial Regex A39Regex();

    [GeneratedRegex(@"\.RequestClose\s*[+-]=")]
    private static partial Regex A40Regex();

    [GeneratedRegex(@"\.(OpenUrl|OpenFolder|OpenFile|ShowInFolder)\s*\(")]
    private static partial Regex A41Regex();

    [GeneratedRegex(@"\bThread\.Sleep\s*\(|\bnew\s+HttpClient\s*\(\s*\)|\bHttpClient\??\s+\w+\s*=\s*new\s*\(|\bProcess\.Start\s*\(")]
    private static partial Regex A42Regex();

    [GeneratedRegex(@"\bcatch\s*(\([^)]*\)\s*)?(when\s*\([^)]*\)\s*)?\{\s*\}")]
    private static partial Regex A43Regex();

    [GeneratedRegex(@"catch\s*\(\s*(?:(?:System\.)?OperationCanceledException|(?:System\.Threading\.Tasks\.)?TaskCanceledException)\b[^)]*\)\s*(?:when\s*\([^)]*\)\s*)?\{(?!(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*(?:\bthrow\b|\w*[Ll]ogger\b|\bAppLogging\b|(?<!\w)_?ui\.|\bNotify\w*\(|\bShow\w*\())")]
    private static partial Regex A44Regex();

    [GeneratedRegex(@"\{\s*Binding\b")]
    private static partial Regex A45Regex();

    #endregion
}
