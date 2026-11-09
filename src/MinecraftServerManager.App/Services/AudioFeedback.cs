using System.Runtime.InteropServices;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 提供標準 Windows 系統音效回饋輔助工具（透過 Win32 MessageBeep 原生 API 播放）
/// </summary>
public static partial class AudioFeedback
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AudioFeedback));
    private const uint MB_ICONHAND = 0x00000010;
    private const uint MB_ICONEXCLAMATION = 0x00000030;
    private const uint MB_ICONASTERISK = 0x00000040;

    [LibraryImport("user32.dll")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool MessageBeep(uint uType);

    /// <summary>
    /// 依訊息層級播放對應之系統音效
    /// </summary>
    public static void Play(UiMessageLevel level)
    {
        switch (level)
        {
            case UiMessageLevel.Question:
                PlayQuestion();
                break;
            case UiMessageLevel.Warning:
                PlayWarning();
                break;
            case UiMessageLevel.Error:
                PlayError();
                break;
            case UiMessageLevel.Information:
            default:
                PlayInfo();
                break;
        }
    }

    /// <summary>
    /// 依提示層級播放對應之系統音效
    /// </summary>
    public static void Play(NotificationLevel level)
    {
        switch (level)
        {
            case NotificationLevel.Error:
                PlayError();
                break;
            case NotificationLevel.Warning:
            default:
                PlayWarning();
                break;
        }
    }

    /// <summary>
    /// 播放警告音效
    /// </summary>
    public static void PlayWarning() => PlayCore(MB_ICONEXCLAMATION, "播放警告提示音效失敗");

    /// <summary>
    /// 播放錯誤音效
    /// </summary>
    public static void PlayError() => PlayCore(MB_ICONHAND, "播放錯誤提示音效失敗");

    /// <summary>
    /// 播放確認詢問音效
    /// </summary>
    public static void PlayQuestion() => PlayCore(MB_ICONASTERISK, "播放詢問提示音效失敗");

    /// <summary>
    /// 播放提示資訊音效
    /// </summary>
    public static void PlayInfo() => PlayCore(MB_ICONASTERISK, "播放資訊提示音效失敗");

    private static void PlayCore(uint uType, string errorMessage)
    {
        try
        {
            MessageBeep(uType);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, errorMessage);
        }
    }
}
