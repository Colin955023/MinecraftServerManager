using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 待安裝模組清單視窗（原生模態視窗，透過 ModalWindowHost 裝載）
/// </summary>
public sealed partial class ModInstallQueueDialog : Window
{
    public ObservableCollection<ModInstallQueueItem> Queue { get; }
    public bool? DialogResult { get; private set; }

    public ModInstallQueueDialog(ObservableCollection<ModInstallQueueItem> queue)
    {
        Queue = queue;
        InitializeComponent();
        Title = "待安裝模組清單";

        WindowLayoutHelper.ResizeToDip(this, 800, 540);
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

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e) => Queue.SortBy(TableSortKeys.InstallQueue, e);

    private void OnHeaderAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(Queue, TableSortKeys.InstallQueue);
}
