using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用 Java 需求服務：固定回報指定 major，不連網</summary>
internal sealed class FixedJavaRequirementService(int major = 21) : IMinecraftJavaRequirementService
{
    public Task<int> GetRequiredJavaMajorAsync(string minecraftVersion, CancellationToken cancellationToken = default) => Task.FromResult(major);

    public int? GetCachedJavaMajor(string minecraftVersion) => major;

    public Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(bool force = false, CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyDictionary<string, int>>(new Dictionary<string, int>());

    public IReadOnlyList<int> GetCachedAvailableJavaMajors() => [major];

    public void ReloadCache()
    {
    }
}

/// <summary>測試用 Java 偵測器：回報固定清單（預設為單一指定 major 的測試主機執行檔），不實際掃描系統</summary>
internal sealed class FixedJavaRuntimeDetector : IJavaRuntimeDetector
{
    private readonly List<JavaRuntimeInfo> _runtimes;

    /// <summary>單一執行環境；預設路徑為測試主機執行檔</summary>
    public FixedJavaRuntimeDetector(int major = 21, string? executablePath = null)
        : this([new JavaRuntimeInfo(executablePath ?? Environment.ProcessPath ?? "java.exe", major)])
    {
    }

    /// <summary>多筆執行環境清單</summary>
    public FixedJavaRuntimeDetector(IEnumerable<JavaRuntimeInfo> runtimes)
    {
        _runtimes = [.. runtimes];
    }

    /// <summary>新增執行環境，之後的偵測與比對皆可見</summary>
    public void Add(JavaRuntimeInfo runtime) => _runtimes.Add(runtime);

    public Task<IReadOnlyList<JavaRuntimeInfo>> DetectAsync(bool forceRefresh = false, CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyList<JavaRuntimeInfo>>(_runtimes.AsReadOnly());

    public Task<JavaRuntimeInfo?> FindBestMatchAsync(int targetMajor, CancellationToken cancellationToken = default) =>
        Task.FromResult(_runtimes.FirstOrDefault(runtime => runtime.MajorVersion == targetMajor));
}
