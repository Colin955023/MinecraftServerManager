using Microsoft.UI.Xaml.Controls;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 通知提示類型：資訊、成功與警告以 InfoBar 顯示，錯誤以對話方塊顯示
/// </summary>
public enum NotificationType
{
    Info,
    Success,
    Warning,
    Error,
}

/// <summary>
/// 通知提示呈現規則：資訊、成功與警告使用 WinUI 原生 InfoBar，錯誤使用對話方塊
/// </summary>
public static class NotificationPresentation
{
    /// <summary>
    /// 將提示類型轉為 InfoBar 嚴重性（錯誤改走對話方塊，不會以 InfoBar 呈現）
    /// </summary>
    public static InfoBarSeverity ToSeverity(NotificationType type) => type switch
    {
        NotificationType.Success => InfoBarSeverity.Success,
        NotificationType.Warning => InfoBarSeverity.Warning,
        _ => InfoBarSeverity.Informational,
    };

    /// <summary>
    /// 是否以對話方塊顯示（錯誤需使用者確認；資訊、成功與警告以 InfoBar 浮動顯示）
    /// </summary>
    public static bool UsesDialog(NotificationType type) => type == NotificationType.Error;

    /// <summary>
    /// InfoBar 自動關閉秒數：警告停留較久以便閱讀
    /// </summary>
    public static int GetDisplaySeconds(NotificationType type) => type == NotificationType.Warning ? 8 : 3;

    /// <summary>
    /// 未指定標題時的預設標題
    /// </summary>
    public static string GetDefaultTitle(NotificationType type) => type switch
    {
        NotificationType.Success => "完成",
        NotificationType.Warning => "警告",
        NotificationType.Error => "錯誤",
        _ => "提示",
    };
}
