using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

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

        AppWindow.Resize(new Windows.Graphics.SizeInt32(800, 540));
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

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (Queue.Count <= 1)
        {
            return;
        }

        Queue.SortBy(e);
    }

    private void OnHeaderAutoFitRequested(object? sender, string propertyName)
    {
        if (Queue.Count == 0)
        {
            return;
        }

        var cols = ModQueueListColumns.Current;
        switch (propertyName)
        {
            case "ActionText":
                cols.ActionWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModQueueListColumns.DefaultActionWidth, Queue.Select(q => q.ActionText), "動作"));
                break;
            case "Title":
                cols.TitleWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModQueueListColumns.DefaultTitleWidth, Queue.Select(q => q.Title), "模組名稱"));
                break;
            case "VersionDisplay":
                cols.VersionWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModQueueListColumns.DefaultVersionWidth, Queue.Select(q => q.VersionDisplay), "版本"));
                break;
            case "FileName":
                cols.FileNameWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModQueueListColumns.DefaultFileNameWidth, Queue.Select(q => q.FileName), "檔案名稱"));
                break;
            case "Reason":
                cols.ReasonWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModQueueListColumns.DefaultReasonWidth, Queue.Select(q => q.Reason), "原因 / 說明"));
                break;
        }
    }
}
