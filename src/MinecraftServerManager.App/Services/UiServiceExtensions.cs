namespace MinecraftServerManager.App.Services;

/// <summary><see cref="IUiService"/> 擴充方法</summary>
public static class UiServiceExtensions
{
    /// <summary>以預設標題顯示通知</summary>
    public static void Notify(this IUiService ui, string message, NotificationType type = NotificationType.Info)
    {
        ArgumentNullException.ThrowIfNull(ui);
        ui.ShowNotification(message, NotificationPresentation.GetDefaultTitle(type), type);
    }
}
