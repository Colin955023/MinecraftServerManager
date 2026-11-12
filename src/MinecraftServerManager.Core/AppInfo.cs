using System.Reflection;

namespace MinecraftServerManager.Core;

/// <summary>應用程式資訊與版本常數</summary>
public static class AppInfo
{
    public const string AppName = "Minecraft 伺服器管理器";
    public const string AppId = "MinecraftServerManager";

    /// <summary>應用程式語意化版本號碼（動態自組件屬性讀取，以 Directory.Build.props 為單一事實來源）</summary>
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

        if (string.IsNullOrWhiteSpace(informationalVersion))
        {
            return typeof(AppInfo).Assembly.GetName().Version?.ToString(3) ?? "0.0.0";
        }

        int separatorIndex = informationalVersion.IndexOf('+', StringComparison.Ordinal);
        return separatorIndex >= 0 ? informationalVersion[..separatorIndex] : informationalVersion;
    }
}
