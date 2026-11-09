namespace MinecraftServerManager.App.Services;

/// <summary>
/// <see cref="IUiService"/> 的便利擴充：以預設標題顯示通知
/// </summary>
public static class UiServiceExtensions
{
    /// <summary>
    /// 顯示提示：錯誤以對話方塊、其餘以 InfoBar 呈現（執行緒封送由 <see cref="IUiService.ShowNotification"/> 負責）
    /// </summary>
    public static void Notify(this IUiService ui, string message, NotificationType type = NotificationType.Info)
    {
        ArgumentNullException.ThrowIfNull(ui);
        ui.ShowNotification(message, NotificationPresentation.GetDefaultTitle(type), type);
    }
}
