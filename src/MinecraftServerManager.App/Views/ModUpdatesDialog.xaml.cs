using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>發現模組更新對話視窗（原生模態視窗，透過 ModalWindowHost 裝載）</summary>
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
        ModalWindowHost.ConfigureDialogWindow(this, "發現模組更新", 800, 540, Bindings.StopTracking);
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
            _ui.ShowNotification("請至少勾選一個要更新的模組！", "未勾選項目", NotificationType.Warning);
            return;
        }

        DialogResult = true;
        Close();
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e) => CandidateItems.SortBy(TableSortKeys.UpdateCandidates, e);

    private void OnHeaderAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(CandidateItems, TableSortKeys.UpdateCandidates);
}
