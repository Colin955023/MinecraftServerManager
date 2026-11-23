using System.Runtime.InteropServices;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Services;

/// <summary>載入內嵌圖示並指派至 AppWindow</summary>
public static partial class WindowIconHelper
{
    private const nint IDI_APPLICATION = 32512;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(WindowIconHelper));
    private static readonly Lock SyncLock = new();
    private static IconId? s_cachedIconId;

    [LibraryImport("kernel32.dll", EntryPoint = "GetModuleHandleW", StringMarshalling = StringMarshalling.Utf16)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial IntPtr GetModuleHandle(string? lpModuleName);

    [LibraryImport("user32.dll", EntryPoint = "LoadIconW")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial IntPtr LoadIcon(IntPtr hInstance, IntPtr lpIconName);

    /// <summary>為指定的 AppWindow 套用應用程式主圖示</summary>
    public static void SetIcon(AppWindow appWindow)
    {
        ArgumentNullException.ThrowIfNull(appWindow);

        lock (SyncLock)
        {
            if (s_cachedIconId.HasValue)
            {
                appWindow.SetIcon(s_cachedIconId.Value);
                return;
            }

            try
            {
                IntPtr hModule = GetModuleHandle(null);
                IntPtr hIcon = LoadIcon(hModule, IDI_APPLICATION);
                if (hIcon != IntPtr.Zero)
                {
                    IconId iconId = Win32Interop.GetIconIdFromIcon(hIcon);
                    s_cachedIconId = iconId;
                    appWindow.SetIcon(iconId);
                }
            }
            catch (Exception ex)
            {
                Logger.Warning(ex, "載入視窗主圖示資源失敗，維持系統預設圖示");
            }
        }
    }
}
