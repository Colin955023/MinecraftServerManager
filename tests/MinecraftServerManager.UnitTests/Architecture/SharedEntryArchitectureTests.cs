using System.Text.RegularExpressions;
using System.Xml.Linq;
using Xunit;

namespace MinecraftServerManager.UnitTests.Architecture;
/// <summary>
/// 原生架構測試（A1～A31 規則）：
/// 規定「共用工具入口」與架構分層界線；規則編號與 docs/TECHNICAL_OVERVIEW.md 第 11 節對照表一一對應。
/// 零額外第三方相依、純原生靜態原始碼掃描與專案結構檢查。
/// </summary>
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

    private static List<string> GetProjectReferences(string csprojPath)
    {
        if (!File.Exists(csprojPath))
        {
            throw new FileNotFoundException($"找不到專案檔：{csprojPath}");
        }

        var doc = XDocument.Load(csprojPath);
        return [.. doc.Descendants("ProjectReference")
            .Select(x => (string?)x.Attribute("Include") ?? string.Empty)
            .Where(x => !string.IsNullOrWhiteSpace(x))];
    }

    #endregion

    #region 規則表（A1～A31，A9 另以專案參照檢查）

    private const string Infra = "src/MinecraftServerManager.Infrastructure/";
    private const string Core = "src/MinecraftServerManager.Core/";
    private const string Domain = "src/MinecraftServerManager.Domain/";
    private const string App = "src/MinecraftServerManager.App/";

    private static readonly string[] Src = ["src"];

    /// <summary>架構規則：掃描範圍、違規正規式、說明、白名單判定與是否保留字串常值（僅清除註解）</summary>
    private sealed record Rule(
        string Id,
        string[] Scopes,
        Regex Pattern,
        string Message,
        Func<string, bool> IsAllowed,
        bool PreserveStrings = false);

    private static Func<string, bool> Allow(params string[] paths) =>
        path => paths.Any(allowed => string.Equals(path, allowed, StringComparison.OrdinalIgnoreCase));

    private static bool StartsWith(string path, string prefix) =>
        path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);

    private static readonly Func<string, bool> AllowNone = static _ => false;

    /// <summary>規則編號與 docs/TECHNICAL_OVERVIEW.md 第 11 節對照表一一對應</summary>
    private static readonly Dictionary<string, Rule> Rules = new Rule[]
    {
        new("A1", Src, A1Regex(), "檔案系統 I/O 必須統一透過 SafeFileSystem 或 AtomicFileWriter",
            path => StartsWith(path, Infra + "FileSystem/") ||
                Allow(Infra + "Utilities/AtomicFileWriter.cs", Infra + "Logging/RotatingFileLoggerProvider.cs", Infra + "Http/HttpDownloadClient.cs")(path)),

        new("A2", Src, A2Regex(), "壓縮檔操作與單一項目讀取必須透過 SafeZipArchive（OpenXmlSpreadsheetBuilder 僅限記憶體建構例外）",
            Allow(Infra + "FileSystem/SafeZipArchive.cs", Infra + "Utilities/OpenXmlSpreadsheetBuilder.cs")),

        new("A3", Src, A3Regex(), "外部行程管理必須統一由 ProcessRunner 負責",
            Allow(Infra + "Process/ProcessRunner.cs")),

        new("A4", Src, A4Regex(), "HttpClient 與處理常式僅得於 AppCompositionRoot 集中建立",
            Allow(App + "AppCompositionRoot.cs")),

        new("A5", Src, A5Regex(), "JSON 解析與序列化必須透過 JsonCodec（IHttpPort 僅保留最小後備）",
            Allow(Infra + "Utilities/JsonCodec.cs", Core + "Ports/IHttpPort.cs")),

        new("A6", Src, A6Regex(), "正規表示式一律使用 [GeneratedRegex]，禁止執行期動態建構或靜態方法呼叫", AllowNone),

        new("A7", Src, A7Regex(), "UI 派送、檔案選取器、對話方塊、訊息框與計時器必須由 IUiService (WinUiService) 統一管理",
            path => Allow(App + "Services/WinUiService.cs", App + "App.xaml.cs", App + "MainWindow.xaml.cs")(path) ||
                StartsWith(path, App + "Views/")),

        new("A8", ["src", "tests"], A8Regex(), "專案全境嚴格禁止 unsafe 程式碼", AllowNone),

        new("A10", [App + "ViewModels"], A10Regex(), "ViewModel 嚴禁持有原生 Process 實體", AllowNone),

        new("A11", Src, A11Regex(), "檔案與資料雜湊計算必須統一經由 HashCalculator（HttpDownloadClient 僅限續傳下載串流例外）",
            Allow(Infra + "Utilities/HashCalculator.cs", Infra + "Http/HttpDownloadClient.cs")),

        new("A12", Src, A12Regex(), "記錄輸出必須統一由 AppLogging 與 ComponentLogger 管理，禁止直呼 Console、Trace 或 Debug 輸出", AllowNone),

        new("A13", [App + "ViewModels"], A13Regex(), "ViewModel 內禁止出現裸 _ = XxxAsync(，必須經由 ViewModelBase.RunSafeAsync 統一處理例外與記錄", AllowNone),

        new("A14", Src, A14Regex(), "系統提示音效必須統一由 AudioFeedback 提供",
            Allow(App + "Services/AudioFeedback.cs")),

        new("A15", Src, A15Regex(), "全專案嚴格禁止使用 Debug 或 Trace 等級輸出日誌（一般使用 Information，非致命例外使用 Warning，嚴重錯誤使用 Error）", AllowNone),

        new("A16", Src, A16Regex(), "視窗標題列、系統強調色、模態視窗繫結與圖示資源載入必須統一由專屬服務管理",
            Allow(App + "Services/TitleBarThemeHelper.cs", App + "Services/AccentColorService.cs", App + "Services/ModalWindowHost.cs", App + "Services/WindowIconHelper.cs")),

        new("A17", Src, A17Regex(), "Windows 保留裝置名稱檢查必須統一使用 ServerName.IsWindowsDeviceName，模組檔名與雜湊挑選必須統一使用 ModHelpers",
            Allow(Domain + "ValueObjects/ServerName.cs", Core + "Mods/ModHelpers.cs"), PreserveStrings: true),

        new("A18", Src, A18Regex(), "例外攔截必須指定型別（如 catch (Exception ex) when (ex is not OperationCanceledException)）並記錄日誌或通知使用者", AllowNone),

        new("A19", Src, A19Regex(), "模組檔案副檔名判斷必須統一使用 ModHelpers（Domain 層 OnlineModVersion 因相依方向例外）",
            Allow(Core + "Mods/ModHelpers.cs", Domain + "Mods/OnlineModVersion.cs"), PreserveStrings: true),

        new("A20", Src, A20Regex(), "版本快取檔名、Mojang Manifest 與 PaperMC API 端點必須統一由 MojangVersionCatalog 提供",
            Allow(Infra + "Loaders/MojangVersionCatalog.cs"), PreserveStrings: true),

        new("A21", Src, A21Regex(), "原生 Win32 互通宣告必須集中於 App.xaml.cs、AudioFeedback、ModalWindowHost、WindowIconHelper、WindowLayoutHelper",
            Allow(App + "App.xaml.cs", App + "Services/AudioFeedback.cs", App + "Services/ModalWindowHost.cs", App + "Services/WindowIconHelper.cs", App + "Services/WindowLayoutHelper.cs")),

        new("A22", Src, A22Regex(), "系統資料夾路徑查詢必須統一使用 RuntimePaths",
            Allow(Infra + "Utilities/RuntimePaths.cs")),

        new("A23", Src, A23Regex(), "必須使用 Path.IsPathFullyQualified 與 Path.TrimEndingDirectorySeparator（SafeZipArchive 拒絕任何具根路徑之壓縮項目為例外）",
            Allow(Infra + "FileSystem/SafeZipArchive.cs")),

        new("A24", [Core.TrimEnd('/'), Infra.TrimEnd('/')], A24Regex(), "Core／Infrastructure 進度轉接必須使用 SynchronousProgress<T>", AllowNone),

        new("A25", Src, A25Regex(), "表格排序必須統一使用 TableSortExtensions.SortBy",
            Allow(App + "Controls/NaturalSortHelper.cs", App + "Controls/TableSortExtensions.cs")),

        new("A26", Src, A26Regex(), "暫存檔命名必須統一使用 AtomicFileWriter.CreateTempSiblingPath",
            Allow(Infra + "Utilities/AtomicFileWriter.cs"), PreserveStrings: true),

        new("A27", Src, A27Regex(), "ANSI 清洗必須使用 ModHelpers.StripColorAndFormattingCodes，記憶體參數必須使用 MemoryUtils",
            Allow(Core + "Mods/ModHelpers.cs", Core + "Utilities/MemoryUtils.cs"), PreserveStrings: true),

        new("A28", Src, A28Regex(), "LoaderKind 解析必須統一使用 LoaderKinds",
            Allow(Domain + "Servers/LoaderKinds.cs")),

        new("A29", Src, A29Regex(), "ViewModel 與 View 的檔案 I/O 必須經由 Core 連接埠注入，不得直接呼叫 Infrastructure 靜態工具",
            path => !StartsWith(path, App + "ViewModels/") && !StartsWith(path, App + "Views/")),

        new("A30", Src, A30Regex(), "視窗尺寸調整必須統一使用 WindowLayoutHelper.ResizeToDip，避免實體像素與邏輯像素混用",
            Allow(App + "Services/WindowLayoutHelper.cs", App + "MainWindow.xaml.cs")),

        new("A31", Src, A31Regex(), "PageServices 僅可出現在組合根與 PageViewModelFactory，ViewModel 不得持有整包服務",
            Allow(App + "AppCompositionRoot.cs", App + "ViewModels/PageServices.cs", App + "ViewModels/PageViewModelFactory.cs")),
    }.ToDictionary(static rule => rule.Id, StringComparer.Ordinal);

    #endregion

    #region 架構規則測試（A1～A31）

    /// <summary>依規則表掃描原始碼並要求零違規；規則編號與技術手冊第 11 節對照表一一對應（A9 見 <see cref="A9_LayerDependencies_ShouldRespectArchitectureBoundaries"/>）</summary>
    [Theory]
    [InlineData("A1")]
    [InlineData("A2")]
    [InlineData("A3")]
    [InlineData("A4")]
    [InlineData("A5")]
    [InlineData("A6")]
    [InlineData("A7")]
    [InlineData("A8")]
    [InlineData("A10")]
    [InlineData("A11")]
    [InlineData("A12")]
    [InlineData("A13")]
    [InlineData("A14")]
    [InlineData("A15")]
    [InlineData("A16")]
    [InlineData("A17")]
    [InlineData("A18")]
    [InlineData("A19")]
    [InlineData("A20")]
    [InlineData("A21")]
    [InlineData("A22")]
    [InlineData("A23")]
    [InlineData("A24")]
    [InlineData("A25")]
    [InlineData("A26")]
    [InlineData("A27")]
    [InlineData("A28")]
    [InlineData("A29")]
    [InlineData("A30")]
    [InlineData("A31")]
    public void Rule_ShouldHaveNoViolations(string ruleId)
    {
        Rule rule = Rules[ruleId];
        var files = rule.Scopes.SelectMany(SourceScanner.GetSourceFiles);
        var violations = SourceScanner.ScanViolations(
            files,
            rule.Pattern,
            rule.Id,
            rule.Message,
            rule.IsAllowed,
            rule.PreserveStrings);

        AssertNoViolations(violations, rule.Id);
    }

    /// <summary>
    /// A9：專案相依性與命名空間界線
    /// 1. 檢查專案參照（Project References）
    /// 2. 檢查 Domain 與 Core 之 using 命名空間界線
    /// 規範：專案規範「架構與專案結構」（相依方向）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A9。
    /// </summary>
    [Fact]
    public void A9_LayerDependencies_ShouldRespectArchitectureBoundaries()
    {
        string domainCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Domain", "MinecraftServerManager.Domain.csproj");
        string coreCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Core", "MinecraftServerManager.Core.csproj");
        string infraCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Infrastructure", "MinecraftServerManager.Infrastructure.csproj");

        var domainRefs = GetProjectReferences(domainCsproj);
        Assert.True(domainRefs.Count == 0, $"Domain 專案不得參照任何外部專案，目前參照：{string.Join(", ", domainRefs)}");

        var coreRefs = GetProjectReferences(coreCsproj);
        Assert.True(
            coreRefs.All(r => r.Contains("MinecraftServerManager.Domain", StringComparison.OrdinalIgnoreCase)),
            $"Core 專案僅得參照 Domain 專案，目前參照：{string.Join(", ", coreRefs)}");

        var infraRefs = GetProjectReferences(infraCsproj);
        Assert.False(
            infraRefs.Any(r => r.Contains("MinecraftServerManager.App", StringComparison.OrdinalIgnoreCase)),
            $"Infrastructure 專案不得逆向參照 App 專案，目前參照：{string.Join(", ", infraRefs)}");

        var domainFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.Domain");
        var domainViolations = SourceScanner.ScanViolations(
            domainFiles,
            A9DomainUsingRegex(),
            "A9",
            "Domain 核心領域層不得 using System.IO、System.Net 或 System.Diagnostics",
            _ => false);
        AssertNoViolations(domainViolations, "A9-Domain");

        var coreFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.Core");
        var coreViolations = SourceScanner.ScanViolations(
            coreFiles,
            A9CoreUsingRegex(),
            "A9",
            "Core 業務核心層不得 using System.IO、System.Net.Http 或 System.Diagnostics",
            _ => false);
        AssertNoViolations(coreViolations, "A9-Core");
    }

    #endregion

    #region 規則比對正規式（A1～A31）

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.)?(File\.|Directory\.|FileInfo\b|DirectoryInfo\b|FileStream\b|DriveInfo\b))")]
    private static partial Regex A1Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.Compression\.)?(ZipFile\.|ZipFile\b)|new\s+(System\.IO\.Compression\.)?ZipArchive\b|\b\w*Entry\w*\.Open\(\))")]
    private static partial Regex A2Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Diagnostics\.)?(Process\.Start\b|ProcessStartInfo\b)|new\s+(System\.Diagnostics\.)?Process\()")]
    private static partial Regex A3Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.Net\.Http\.)?HttpClient\b|SocketsHttpHandler\b|HttpClientHandler\b)")]
    private static partial Regex A4Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Text\.Json\.)?(JsonSerializer\.|JsonDocument\.)|new\s+(System\.Text\.Json\.)?JsonSerializerOptions\b)")]
    private static partial Regex A5Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.Text\.RegularExpressions\.)?Regex\(|(System\.Text\.RegularExpressions\.)?Regex\.(IsMatch|Match|Matches|Replace|Split)\()")]
    private static partial Regex A6Regex();

    [GeneratedRegex(@"(?<![\w\.])(MessageBoxW\b|DispatcherTimer\b|DispatcherQueueTimer\b|FileOpenPicker\b|FileSavePicker\b|FolderPicker\b|new\s+ContentDialog\b)|\.CreateTimer\(")]
    private static partial Regex A7Regex();

    [GeneratedRegex(@"(?<![\w\.])unsafe\b")]
    private static partial Regex A8Regex();

    [GeneratedRegex(@"^\s*using\s+System\.(IO|Net|Diagnostics)\b")]
    private static partial Regex A9DomainUsingRegex();

    [GeneratedRegex(@"^\s*using\s+System\.(IO|Net\.Http|Diagnostics)\b")]
    private static partial Regex A9CoreUsingRegex();

    [GeneratedRegex(@"(?<![\w\.])(System\.Diagnostics\.Process\b|\bProcess\s+[A-Za-z_])")]
    private static partial Regex A10Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Security\.Cryptography\.)?(SHA256\.|SHA1\.|MD5\.|SHA512\.|IncrementalHash\b|HashAlgorithm\.|HashAlgorithmName\.|CryptographicOperations\.HashData\b)|System\.Security\.Cryptography\.HashAlgorithm\b)")]
    private static partial Regex A11Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.)?Console\.(WriteLine|Write)|(System\.Diagnostics\.)?(Trace|Debug)\.(WriteLine|Write|TraceInformation|TraceWarning|TraceError))\(")]
    private static partial Regex A12Regex();

    [GeneratedRegex(@"(?<![\w\.])_\s*=\s*(?!(?:ViewModelBase\.)?RunSafeAsync\b)(?:([a-zA-Z_]\w*\.)*([a-zA-Z_]\w*Async)|Task\.Run)\(")]
    private static partial Regex A13Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Media\.)?(SystemSounds\b|SoundPlayer\b)|MessageBeep\b)")]
    private static partial Regex A14Regex();

    [GeneratedRegex(@"(?<![\w\.])(?:\bLogger|\blogger|\bLog)\.(Debug|Trace|LogDebug|LogTrace)\(")]
    private static partial Regex A15Regex();

    [GeneratedRegex(@"(?<![\w\.])(AppWindowTitleBar\b|UISettings\b|SetWindowLongPtrW\b|LoadIconW\b)")]
    private static partial Regex A16Regex();

    [GeneratedRegex(@"(""CLOCK\$""|""PRN""|(?<!ModHelpers\.)\bModFilenameStem\s*\(|(?<!ModHelpers\.)\bResolveHash\s*\(\s*ModFile)")]
    private static partial Regex A17Regex();

    [GeneratedRegex(@"(?<![\w\.])catch\s*(\{|$)")]
    private static partial Regex A18Regex();

    [GeneratedRegex(@"EndsWith\(\s*""\.jar|\.jar\.disabled""")]
    private static partial Regex A19Regex();

    [GeneratedRegex(@"mc_versions_cache\.json|piston-meta\.mojang\.com|fill\.papermc\.io")]
    private static partial Regex A20Regex();

    [GeneratedRegex(@"\[\s*(LibraryImport|DllImport)\b")]
    private static partial Regex A21Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.)?Environment\.GetFolderPath|(System\.IO\.)?Path\.GetTempPath)\b")]
    private static partial Regex A22Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.)?Path\.IsPathRooted\(|\.TrimEnd\(\s*(System\.IO\.)?Path\.(Alt)?DirectorySeparatorChar)")]
    private static partial Regex A23Regex();

    [GeneratedRegex(@"(?<![\w\.])new\s+(System\.)?Progress<")]
    private static partial Regex A24Regex();

    [GeneratedRegex(@"(?<![\w\.])new\s+SortKeyComparer\b|\bSortKeyComparer\.Instance\b")]
    private static partial Regex A25Regex();

    [GeneratedRegex(@"\.tmp""")]
    private static partial Regex A26Regex();

    [GeneratedRegex(@"GeneratedRegex\(.*(\\x1B|\\u001[bB]|-Xm[xs]|Xmx\|Xms)")]
    private static partial Regex A27Regex();

    [GeneratedRegex(@"Enum\.(TryParse|Parse)\s*<\s*LoaderKind\s*>")]
    private static partial Regex A28Regex();

    [GeneratedRegex(@"(?<![\w\.])(SafeFileSystem|ModFileInstaller|ServersRootRelocator|PropertiesDocumentCodec)\.")]
    private static partial Regex A29Regex();

    [GeneratedRegex(@"\bAppWindow\.Resize\(")]
    private static partial Regex A30Regex();

    [GeneratedRegex(@"\bPageServices\b")]
    private static partial Regex A31Regex();

    #endregion
}
