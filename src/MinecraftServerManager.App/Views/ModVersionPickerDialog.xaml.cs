using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 模組版本選擇對話方塊（原生模態視窗，透過 ModalWindowHost 裝載）
/// </summary>
public sealed partial class ModVersionPickerDialog : Window
{
    public ModVersionPickerViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public ModVersionPickerDialog(ModVersionPickerViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        Title = "選擇模組版本";

        AppWindow.Resize(new Windows.Graphics.SizeInt32(820, 560));

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            Close();
        };
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (ViewModel.Versions.Count <= 1)
        {
            return;
        }

        ViewModel.Versions.SortBy(e);
    }

    private void OnHeaderAutoFitRequested(object? sender, string propertyName)
    {
        if (ViewModel.Versions.Count == 0)
        {
            return;
        }

        var cols = ModVersionListColumns.Current;
        switch (propertyName)
        {
            case "VersionNumber":
                cols.VersionWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModVersionListColumns.DefaultVersionWidth, ViewModel.Versions.Select(v => v.VersionNumber), "版本號碼"));
                break;
            case "GameVersions":
                cols.GameVersionWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModVersionListColumns.DefaultGameVersionWidth, ViewModel.Versions.Select(v => v.GameVersions), "支援 MC"));
                break;
            case "Loaders":
                cols.LoaderWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModVersionListColumns.DefaultLoaderWidth, ViewModel.Versions.Select(v => v.Loaders), "載入器"));
                break;
            case "DatePublished":
                cols.DateWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModVersionListColumns.DefaultDateWidth, ViewModel.Versions.Select(v => v.DatePublished), "發布時間"));
                break;
            case "FileName":
                cols.FileNameWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModVersionListColumns.DefaultFileNameWidth, ViewModel.Versions.Select(v => v.FileName), "檔案"));
                break;
        }
    }
}
