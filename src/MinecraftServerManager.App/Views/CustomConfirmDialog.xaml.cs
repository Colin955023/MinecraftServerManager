using System.Windows;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 提供深淺色主題相容、鍵盤導航與原生音效回饋的自訂確認視窗
/// </summary>
public partial class CustomConfirmDialog : Window
{
    private readonly UiMessageLevel _level;

    public CustomConfirmDialog(string title, string message, UiMessageLevel level = UiMessageLevel.Question)
    {
        InitializeComponent();

        _level = level;
        Title = title;
        TitleText.Text = title;
        MessageText.Text = message;

        switch (level)
        {
            case UiMessageLevel.Error:
                IconText.Text = "❌";
                ConfirmButton.SetResourceReference(StyleProperty, "DangerButtonStyle");
                break;
            case UiMessageLevel.Warning:
                IconText.Text = "⚠️";
                ConfirmButton.SetResourceReference(StyleProperty, "DangerButtonStyle");
                break;
            case UiMessageLevel.Information:
                IconText.Text = "ℹ️";
                break;
            case UiMessageLevel.Question:
            default:
                IconText.Text = "❓";
                break;
        }
    }

    private void Window_Loaded(object sender, RoutedEventArgs e)
    {
        switch (_level)
        {
            case UiMessageLevel.Error:
                AudioFeedback.PlayError();
                break;
            case UiMessageLevel.Warning:
                AudioFeedback.PlayWarning();
                break;
            case UiMessageLevel.Information:
                AudioFeedback.PlayInfo();
                break;
            case UiMessageLevel.Question:
            default:
                AudioFeedback.PlayQuestion();
                break;
        }
    }

    private void ConfirmButton_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = true;
        Close();
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    /// <summary>
    /// 顯示確認對話方塊並回傳使用者選擇結果
    /// </summary>
    public static bool Show(Window? owner, string message, string title, UiMessageLevel level = UiMessageLevel.Question)
    {
        var dialog = new CustomConfirmDialog(title, message, level);
        if (owner is not null && owner.IsLoaded && owner.IsVisible)
        {
            dialog.Owner = owner;
            dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner;
        }
        else
        {
            dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen;
        }

        return dialog.ShowDialog() == true;
    }
}
