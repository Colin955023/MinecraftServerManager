using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 測試用 UI 服務：將提示轉送給回呼（訊息、提示類型），其餘行為沿用 <see cref="NoOpUiService"/>
/// </summary>
internal sealed class NotificationCaptureUiService(Action<string, NotificationType> onNotification) : NoOpUiService
{
    public override void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info) =>
        onNotification(message, type);
}
