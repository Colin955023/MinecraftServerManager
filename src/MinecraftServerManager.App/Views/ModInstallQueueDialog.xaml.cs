using System.Collections.ObjectModel;
using System.Windows;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 待安裝模組清單視窗
/// </summary>
public partial class ModInstallQueueDialog : Window
{
    private readonly ObservableCollection<ModInstallQueueItem> _queue;

    public ModInstallQueueDialog(ObservableCollection<ModInstallQueueItem> queue)
    {
        InitializeComponent();
        _queue = queue;
        QueueGrid.ItemsSource = _queue;
    }

    private void ClearQueue_Click(object sender, RoutedEventArgs e) => _queue.Clear();

    private void StartInstall_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = true;
        Close();
    }

    private void Close_Click(object sender, RoutedEventArgs e) => Close();
}
