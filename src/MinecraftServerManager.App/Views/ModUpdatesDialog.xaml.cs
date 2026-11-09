using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 發現模組更新對話視窗（原生模態視窗，透過 ModalWindowHost 裝載）
/// </summary>
public sealed partial class ModUpdatesDialog : Window
{
    private readonly IUiService _ui;

    public BulkObservableCollection<ModUpdateCandidateItem> CandidateItems { get; }
    public bool? DialogResult { get; private set; }

    public ModUpdatesDialog(IEnumerable<ModUpdateCandidateItem> items, IUiService ui)
    {
        ArgumentNullException.ThrowIfNull(ui);
        _ui = ui;
        CandidateItems = new BulkObservableCollection<ModUpdateCandidateItem>(items);
        InitializeComponent();
        Title = "發現模組更新";

        AppWindow.Resize(new Windows.Graphics.SizeInt32(800, 540));
    }

    public IReadOnlyList<ModUpdateCandidateItem> GetSelectedItems() =>
        (ModUpdateCandidateItem[])[.. CandidateItems.Where(static i => i.IsSelected)];

    private void OnSelectAllClicked(object sender, RoutedEventArgs e)
    {
        foreach (var item in CandidateItems)
        {
            item.IsSelected = true;
        }
    }

    private void OnDeselectAllClicked(object sender, RoutedEventArgs e)
    {
        foreach (var item in CandidateItems)
        {
            item.IsSelected = false;
        }
    }

    private void OnCancelClicked(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private void OnUpdateClicked(object sender, RoutedEventArgs e)
    {
        if (!CandidateItems.Any(static i => i.IsSelected))
        {
            _ui.ShowToast("請至少勾選一個要更新的模組！", "未勾選項目", ToastType.Warning);
            return;
        }

        DialogResult = true;
        Close();
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e)
    {
        if (CandidateItems.Count <= 1)
        {
            return;
        }

        CandidateItems.SortBy(e);
    }

    private void OnHeaderAutoFitRequested(object? sender, string propertyName)
    {
        if (CandidateItems.Count == 0)
        {
            return;
        }

        var cols = ModUpdatesListColumns.Current;
        switch (propertyName)
        {
            case "IsSelected":
                cols.UpdateWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModUpdatesListColumns.DefaultUpdateWidth, [], "更新"));
                break;
            case "ModName":
                cols.NameWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModUpdatesListColumns.DefaultNameWidth, CandidateItems.Select(c => c.ModName), "模組名稱"));
                break;
            case "CurrentVersion":
                cols.CurrentVersionWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModUpdatesListColumns.DefaultCurrentVersionWidth, CandidateItems.Select(c => c.CurrentVersion), "目前版本"));
                break;
            case "NewVersion":
                cols.NewVersionWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModUpdatesListColumns.DefaultNewVersionWidth, CandidateItems.Select(c => c.NewVersion), "最新版本"));
                break;
            case "SourcePlatform":
                cols.PlatformWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModUpdatesListColumns.DefaultPlatformWidth, CandidateItems.Select(c => c.SourcePlatform), "來源平台"));
                break;
            case "FileName":
                cols.FileNameWidth = new(SortableTableHeader.CalculateAutoFitWidth(ModUpdatesListColumns.DefaultFileNameWidth, CandidateItems.Select(c => c.FileName), "新檔案名稱"));
                break;
        }
    }
}
