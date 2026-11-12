using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.TestSupport;

/// <summary>測試用 Java 需求服務：固定回報指定 major，不連網</summary>
internal sealed class FixedJavaRequirementService(int major = 21) : IMinecraftJavaRequirementService
{
    public Task<int> GetRequiredJavaMajorAsync(string minecraftVersion, LoaderKind loader = LoaderKind.Unknown, CancellationToken cancellationToken = default) => Task.FromResult(major);

    public int? GetCachedJavaMajor(string minecraftVersion, LoaderKind loader = LoaderKind.Unknown) => major;

    public Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(bool force = false, CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyDictionary<string, int>>(new Dictionary<string, int>());

    public IReadOnlyList<int> GetCachedAvailableJavaMajors() => [major];

    public void ReloadCache()
    {
    }
}

/// <summary>測試用 Java 偵測器：僅有一個指定 major 的執行環境，路徑指向實際存在的檔案</summary>
internal sealed class FixedJavaRuntimeDetector(int major = 21) : IJavaRuntimeDetector
{
    private readonly JavaRuntimeInfo _runtime = new(Environment.ProcessPath ?? "java.exe", major);

    public Task<IReadOnlyList<JavaRuntimeInfo>> DetectAsync(bool forceRefresh = false, CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyList<JavaRuntimeInfo>>([_runtime]);

    public Task<JavaRuntimeInfo?> FindBestMatchAsync(int targetMajor, CancellationToken cancellationToken = default) =>
        Task.FromResult(targetMajor == _runtime.MajorVersion ? _runtime : null);
}
