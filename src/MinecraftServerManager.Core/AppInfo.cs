using System.Reflection;

namespace MinecraftServerManager.Core;

/// <summary>應用程式資訊與版本常數</summary>
public static class AppInfo
{
    public const string AppName = "Minecraft 伺服器管理器";
    public const string AppId = "MinecraftServerManager";

    /// <summary>應用程式版本（讀自組件屬性）</summary>
    public static string Version { get; } = ResolveVersion();

    public const string Author = "Colin955023";
    public const string LicenseUrl = "https://www.gnu.org/licenses/gpl-3.0.html";
    public const string RepositoryUrl = "https://github.com/Colin955023/MinecraftServerManager";
    public const string TargetFramework = ".NET 10 (WinUI 3)";

    private static string ResolveVersion()
    {
        string? informationalVersion = typeof(AppInfo).Assembly
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()
            ?.InformationalVersion;

        // 去除 +建置中繼資料；若僅剩空白（如 "+abc"）則改用組件版本
        ReadOnlySpan<char> version = informationalVersion.AsSpan();
        int separatorIndex = version.IndexOf('+');
        if (separatorIndex >= 0)
        {
            version = version[..separatorIndex];
        }

        version = version.Trim();
        return version.IsEmpty ? FormatAssemblyVersion(typeof(AppInfo).Assembly.GetName().Version) : version.ToString();
    }

    /// <summary>組件版本格式化為三段；不足三段者以 0 補齊</summary>
    private static string FormatAssemblyVersion(Version? version) =>
        version is null ? "0.0.0" : $"{version.Major}.{version.Minor}.{Math.Max(version.Build, 0)}";
}
