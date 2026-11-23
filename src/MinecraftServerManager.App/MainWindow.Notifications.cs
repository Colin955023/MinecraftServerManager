using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App;

public sealed partial class MainWindow
{
    /// <summary>以 InfoBar 顯示資訊、成功與警告通知</summary>
    public void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info, int? durationSeconds = null) =>
        ShowInfoBar(
            title ?? NotificationPresentation.GetDefaultTitle(type),
            message,
            type,
            durationSeconds ?? NotificationPresentation.GetDisplaySeconds(type));

    /// <summary>於右上角顯示 InfoBar 通知：滑鼠停留時暫停關閉，最多 4 則</summary>
    private void ShowInfoBar(string title, string message, NotificationType type, int durationSeconds)
    {
        var infoBar = new InfoBar
        {
            Title = title,
            Message = message,
            Severity = NotificationPresentation.ToSeverity(type),
            IsClosable = true,
            IsOpen = true,
        };
        Controls.InfoBarThemeRefresh.SetIsEnabled(infoBar, true);

        // InfoBar 預設背景為半透明，外層以不透明底色（ThemeResource，隨主題切換）承載確保浮於頁面內容上仍清晰可讀
        var host = new Border
        {
            Style = (Style)Application.Current.Resources["NotificationHostStyle"],
            Child = infoBar,
        };

        bool isClosed = false;
        var timer = DispatcherQueue.CreateTimer();
        timer.Interval = TimeSpan.FromSeconds(durationSeconds > 0 ? durationSeconds : 3);
        timer.IsRepeating = false;
        timer.Tick += (_, _) => infoBar.IsOpen = false;

        infoBar.Closed += (_, _) =>
        {
            isClosed = true;
            timer.Stop();
            NotificationContainer.Children.Remove(host);
        };
        host.PointerEntered += (_, _) => timer.Stop();
        host.PointerExited += (_, _) =>
        {
            if (!isClosed)
            {
                timer.Start();
            }
        };

        while (NotificationContainer.Children.Count >= MaxNotifications)
        {
            // 經 IsOpen=false 走 Closed 流程，被擠出之通知一併停止計時器並移除
            if (NotificationContainer.Children[0] is Border { Child: InfoBar { IsOpen: true } oldBar })
            {
                oldBar.IsOpen = false;
            }
            else
            {
                NotificationContainer.Children.RemoveAt(0);
            }
        }

        NotificationContainer.Children.Add(host);
        timer.Start();

        if (type == NotificationType.Warning)
        {
            AudioFeedback.PlayWarning();
        }
        else
        {
            AudioFeedback.PlayInfo();
        }
    }
}
