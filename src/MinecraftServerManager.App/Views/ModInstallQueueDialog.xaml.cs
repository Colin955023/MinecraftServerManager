using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>待安裝模組清單視窗</summary>
public sealed partial class ModInstallQueueDialog : Window
{
    public ObservableCollection<ModInstallQueueItem> Queue { get; }
    public bool? DialogResult { get; private set; }

    public ModInstallQueueDialog(ObservableCollection<ModInstallQueueItem> queue)
    {
        Queue = queue;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, "待安裝模組清單", 800, 540, Bindings.StopTracking);
    }

    private void ClearQueue_Click(object sender, RoutedEventArgs e) => Queue.Clear();

    private void Close_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private void StartInstall_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = true;
        Close();
    }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<ModInstallQueueItem>(() => Queue, TableSortKeys.InstallQueue);
}
