using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Servers;

/// <summary>伺服器啟動計畫（強型別不可變模型）；記憶體須為正數且最小值不大於最大值</summary>
public sealed record ServerLaunchPlan
{
    public ServerLaunchPlan(
        string JavaExecutable,
        string WorkingDirectory,
        IReadOnlyList<string> Arguments,
        LoaderKind Loader,
        int MinMemoryMb,
        int MaxMemoryMb,
        bool IsScript,
        string? ServerName = null,
        IReadOnlyDictionary<string, string?>? Environment = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(JavaExecutable);
        ArgumentException.ThrowIfNullOrWhiteSpace(WorkingDirectory);
        ArgumentNullException.ThrowIfNull(Arguments);
        if (!Enum.IsDefined(Loader))
        {
            throw new ArgumentOutOfRangeException(nameof(Loader), Loader, "未定義的載入器類型");
        }
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(MinMemoryMb);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(MaxMemoryMb);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(MinMemoryMb, MaxMemoryMb);

        this.JavaExecutable = JavaExecutable;
        this.WorkingDirectory = WorkingDirectory;
        this.Arguments = Arguments;
        this.Loader = Loader;
        this.MinMemoryMb = MinMemoryMb;
        this.MaxMemoryMb = MaxMemoryMb;
        this.IsScript = IsScript;
        this.ServerName = ServerName;
        this.Environment = Environment;
    }

    public string JavaExecutable { get; }
    public string WorkingDirectory { get; }
    public IReadOnlyList<string> Arguments { get; }
    public LoaderKind Loader { get; }
    public int MinMemoryMb { get; }
    public int MaxMemoryMb { get; }
    public bool IsScript { get; }
    public string? ServerName { get; }
    public IReadOnlyDictionary<string, string?>? Environment { get; }
}
