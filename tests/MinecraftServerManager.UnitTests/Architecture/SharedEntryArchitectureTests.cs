using System.Text.RegularExpressions;
using System.Xml.Linq;
using Xunit;

namespace MinecraftServerManager.UnitTests.Architecture;
/// <summary>
/// 原生架構測試（A1～A12 規則）：
/// 自動化防護 AGENTS.md 所規定之「共用工具入口」與架構分層界線。
/// 零額外第三方相依、純原生靜態原始碼掃描與專案結構檢查。
/// </summary>
public sealed partial class SharedEntryArchitectureTests
{
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

    [Fact]
    public void A1_FileSystemDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        // 規則 A1：檔案與目錄存在性、走訪、建立、刪除與串流 I/O 一律經由 SafeFileSystem / AtomicFileWriter
        // 禁止直接呼叫 File.、Directory.、FileInfo、DirectoryInfo、FileStream、DriveInfo
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A1Regex(),
            "A1",
            "檔案系統 I/O 必須統一透過 SafeFileSystem 或 AtomicFileWriter",
            path =>
                path.StartsWith("src/MinecraftServerManager.Infrastructure/FileSystem/", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/AtomicFileWriter.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Logging/RotatingFileLoggerProvider.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Http/HttpDownloadClient.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A1");
    }

    [Fact]
    public void A2_ZipDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        // 規則 A2：ZIP / JAR 讀寫解壓一律經由 SafeZipArchive
        // 禁止直接呼叫 ZipFile. 或建構 new ZipArchive
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A2Regex(),
            "A2",
            "壓縮檔操作必須透過 SafeZipArchive（OpenXmlSpreadsheetBuilder 僅限記憶體建構例外）",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/FileSystem/SafeZipArchive.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/OpenXmlSpreadsheetBuilder.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A2");
    }

    [Fact]
    public void A3_ProcessDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        // 規則 A3：外部行程生命週期與 Shell 呼叫一律經由 ProcessRunner
        // 禁止直接呼叫 Process.Start、new Process、ProcessStartInfo
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A3Regex(),
            "A3",
            "外部行程管理必須統一由 ProcessRunner 負責",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Process/ProcessRunner.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A3");
    }

    [Fact]
    public void A4_HttpClientDirectInstantiation_ShouldOnlyBeUsedInAppCompositionRoot()
    {
        // 規則 A4：共用 HttpClient 與 Handler 僅得由組合根建立，外部通訊經由 IHttpPort
        // 禁止 new HttpClient、SocketsHttpHandler、HttpClientHandler
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A4Regex(),
            "A4",
            "HttpClient 與處理常式僅得於 AppCompositionRoot 集中建立",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/AppCompositionRoot.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A4");
    }

    [Fact]
    public void A5_JsonDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        // 規則 A5：JSON 序列化與解析一律透過 JsonCodec，Core 連接埠僅得保留最小回退
        // 禁止 JsonSerializer.、JsonDocument.、new JsonSerializerOptions
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A5Regex(),
            "A5",
            "JSON 解析與序列化必須透過 JsonCodec（IHttpPort 僅保留最小回退）",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/JsonCodec.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Core/Ports/IHttpPort.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A5");
    }

    [Fact]
    public void A6_RegexDirectInstantiationOrStaticCall_ShouldBeZero_MustUseGeneratedRegex()
    {
        // 規則 A6：正規表示式一律採用 [GeneratedRegex] Source Generator 編譯期產生
        // 禁止 new Regex( 或 Regex.IsMatch / Match / Replace / Split 靜態呼叫
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A6Regex(),
            "A6",
            "正規表示式一律使用 [GeneratedRegex]，禁止執行期動態建構或靜態方法呼叫",
            _ => false);

        AssertNoViolations(violations, "A6");
    }

    [Fact]
    public void A7_UiDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        // 規則 A7：訊息框、UI 執行緒派送與計時器一律透過 IUiService
        // 禁止直接呼叫 MessageBox.Show、Dispatcher、DispatcherTimer
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A7Regex(),
            "A7",
            "UI 派送、訊息框與計時器必須由 IUiService 統一管理",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/Services/WpfUiService.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/App.xaml.cs", StringComparison.OrdinalIgnoreCase) ||
                path.StartsWith("src/MinecraftServerManager.App/Views/", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A7");
    }

    [Fact]
    public void A8_UnsafeCode_ShouldBeZeroAcrossSolution()
    {
        // 規則 A8：專案全境嚴格禁止出現 unsafe 區塊或關鍵字
        var files = SourceScanner.GetSourceFiles("src")
            .Concat(SourceScanner.GetSourceFiles("tests"));

        var violations = SourceScanner.ScanViolations(
            files,
            A8Regex(),
            "A8",
            "專案全境嚴格禁止 unsafe 程式碼",
            _ => false);

        AssertNoViolations(violations, "A8");
    }

    [Fact]
    public void A9_LayerDependencies_ShouldRespectArchitectureBoundaries()
    {
        // 規則 A9：專案相依性與命名空間界線
        // 1. 檢查專案參照（Project References）
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

        // 2. 檢查 Domain 與 Core 之 using 命名空間界線
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

    [Fact]
    public void A10_ViewModelBoundaries_ShouldNotHoldProcessOrDirectIoOrHttpClient()
    {
        // 規則 A10：App/ViewModels 不得持有原生 Process 實體、不得直接呼叫 File./Directory.、不得 new HttpClient
        var viewModelFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.App/ViewModels");
        var violations = SourceScanner.ScanViolations(
            viewModelFiles,
            A10Regex(),
            "A10",
            "ViewModel 嚴禁持有原生 Process 實體、直接實體檔案 I/O 或建構 HttpClient",
            _ => false);

        AssertNoViolations(violations, "A10");
    }

    [Fact]
    public void A11_HashDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        // 規則 A11：檔案與資料雜湊一律集中於 HashCalculator，僅 HTTP 續傳下載可在串流中同步計算雜湊
        // 禁止直接呼叫或建構 SHA256、SHA1、MD5、SHA512、IncrementalHash
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A11Regex(),
            "A11",
            "檔案與資料雜湊計算必須統一經由 HashCalculator（HttpDownloadClient 僅限續傳下載串流例外）",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/HashCalculator.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Http/HttpDownloadClient.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A11");
    }

    [Fact]
    public void A12_ConsoleOrDiagnosticsLoggingDirectAccess_ShouldBeZeroAcrossSrc()
    {
        // 規則 A12：記錄管線一律由 AppLogging 與 ComponentLogger 集中管理，禁止直呼 Console/Trace/Debug 輸出
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A12Regex(),
            "A12",
            "記錄輸出必須統一由 AppLogging 與 ComponentLogger 管理，禁止直呼 Console、Trace 或 Debug 輸出",
            _ => false);

        AssertNoViolations(violations, "A12");
    }

    [Fact]
    public void A13_ViewModels_MustNotContainDiscardedAsyncCalls()
    {
        // 規則 A13：App/ViewModels 內禁止出現裸 _ = XxxAsync( 發射後不管呼叫，必須統一呼叫 ViewModelBase.RunSafeAsync
        var files = SourceScanner.GetSourceFiles("src/MinecraftServerManager.App/ViewModels");
        var violations = SourceScanner.ScanViolations(
            files,
            A13Regex(),
            "A13",
            "ViewModel 內禁止出現裸 _ = XxxAsync(，必須經由 ViewModelBase.RunSafeAsync 統一處理例外與記錄",
            _ => false);

        AssertNoViolations(violations, "A13");
    }

    private static List<string> GetProjectReferences(string csprojPath)
    {
        if (!File.Exists(csprojPath))
        {
            throw new FileNotFoundException($"找不到專案檔：{csprojPath}");
        }

        var doc = XDocument.Load(csprojPath);
        return doc.Descendants("ProjectReference")
            .Select(x => (string?)x.Attribute("Include") ?? string.Empty)
            .Where(x => !string.IsNullOrWhiteSpace(x))
            .ToList();
    }

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.)?(File\.|Directory\.|FileInfo\b|DirectoryInfo\b|FileStream\b|DriveInfo\b))")]
    private static partial Regex A1Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.Compression\.)?(ZipFile\.|ZipFile\b)|new\s+(System\.IO\.Compression\.)?ZipArchive\b)")]
    private static partial Regex A2Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Diagnostics\.)?(Process\.Start\b|ProcessStartInfo\b)|new\s+(System\.Diagnostics\.)?Process\()")]
    private static partial Regex A3Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.Net\.Http\.)?HttpClient\b|SocketsHttpHandler\b|HttpClientHandler\b)")]
    private static partial Regex A4Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Text\.Json\.)?(JsonSerializer\.|JsonDocument\.)|new\s+(System\.Text\.Json\.)?JsonSerializerOptions\b)")]
    private static partial Regex A5Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.Text\.RegularExpressions\.)?Regex\(|(System\.Text\.RegularExpressions\.)?Regex\.(IsMatch|Match|Matches|Replace|Split)\()")]
    private static partial Regex A6Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Windows\.)?MessageBox\.Show\b|Dispatcher\.Invoke|Dispatcher\.BeginInvoke|DispatcherTimer\b)")]
    private static partial Regex A7Regex();

    [GeneratedRegex(@"(?<![\w\.])unsafe\b")]
    private static partial Regex A8Regex();

    [GeneratedRegex(@"^\s*using\s+System\.(IO|Net|Diagnostics)\b")]
    private static partial Regex A9DomainUsingRegex();

    [GeneratedRegex(@"^\s*using\s+System\.(IO|Net\.Http|Diagnostics)\b")]
    private static partial Regex A9CoreUsingRegex();

    [GeneratedRegex(@"(?<![\w\.])(System\.Diagnostics\.Process\b|\bProcess\s+[A-Za-z_]|new\s+(System\.Net\.Http\.)?HttpClient\b|(System\.IO\.)?File\.|(System\.IO\.)?Directory\.)")]
    private static partial Regex A10Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Security\.Cryptography\.)?(SHA256\.|SHA1\.|MD5\.|SHA512\.|IncrementalHash\b|HashAlgorithm\.)|System\.Security\.Cryptography\.HashAlgorithm\b)")]
    private static partial Regex A11Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.)?Console\.(WriteLine|Write)|(System\.Diagnostics\.)?(Trace|Debug)\.(WriteLine|Write|TraceInformation|TraceWarning|TraceError))\(")]
    private static partial Regex A12Regex();

    [GeneratedRegex(@"(?<![\w\.])_\s*=\s*(?!(?:ViewModelBase\.)?RunSafeAsync\b)([a-zA-Z_]\w*\.)*([a-zA-Z_]\w*Async)\(")]
    private static partial Regex A13Regex();

    [Fact]
    public void A14_SoundDirectAccess_ShouldOnlyBeUsedInAudioFeedback()
    {
        // 規則 A14：系統提示音效一律經由 AudioFeedback 工具
        // 禁止直接呼叫 SystemSounds 或 new SoundPlayer
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A14Regex(),
            "A14",
            "系統提示音效必須統一由 AudioFeedback 提供",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/Services/AudioFeedback.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A14");
    }

    [GeneratedRegex(@"(?<![\w\.])((System\.Media\.)?(SystemSounds\b|SoundPlayer\b))")]
    private static partial Regex A14Regex();
}
