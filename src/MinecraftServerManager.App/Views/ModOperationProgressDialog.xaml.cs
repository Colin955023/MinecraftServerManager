using System.Windows;

namespace MinecraftServerManager.App.Views;

public partial class ModOperationProgressDialog : Window
{
    public ModOperationProgressDialog(string title, string initialMessage)
    {
        InitializeComponent();
        Title = title;
        TitleText.Text = title;
        PhaseText.Text = initialMessage;
    }

    public void UpdateProgress(int current, int total, string message)
    {
        int pct = total > 0 ? (int)Math.Clamp(current * 100.0 / total, 0, 100) : 0;
        Dispatcher.Invoke(() =>
        {
            PhaseText.Text = message;
            ProgressBarControl.Value = pct;
            PercentText.Text = $"{pct}% ({current}/{total})";
        });
    }

    public void UpdateMessage(string message)
    {
        Dispatcher.Invoke(() =>
        {
            PhaseText.Text = message;
        });
    }
}
