using System.Windows;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 封裝使用者互動對話框，自動防範非 UI/測試環境彈窗阻塞
/// </summary>
public static class DialogHelper
{
    public static bool Confirm(string message, string title, MessageBoxImage image = MessageBoxImage.Question)
    {
        if (Application.Current is null)
        {
            return true;
        }

        return MessageBox.Show(message, title, MessageBoxButton.YesNo, image) == MessageBoxResult.Yes;
    }

    public static void ShowInfo(string message, string title)
    {
        if (Application.Current is not null)
        {
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    public static void ShowWarning(string message, string title)
    {
        if (Application.Current is not null)
        {
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    public static void ShowError(string message, string title)
    {
        if (Application.Current is not null)
        {
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }
}
