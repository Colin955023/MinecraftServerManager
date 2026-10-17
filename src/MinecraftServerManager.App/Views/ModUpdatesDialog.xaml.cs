using System.Collections.ObjectModel;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public sealed partial class ModUpdateCandidateItem : ObservableObject
{
    [ObservableProperty]
    public partial bool IsSelected { get; set; } = true;

    public required string ModName { get; init; }
    public required string CurrentVersion { get; init; }
    public required string NewVersion { get; init; }
    public required string FileName { get; init; }
    public string SourcePlatform { get; init; } = "Modrinth";
    public required string DownloadUrl { get; init; }
    public string? ExpectedHash { get; init; }
    public string? HashAlgorithm { get; init; }
    public required LocalModRowItem LocalMod { get; init; }
}

public partial class ModUpdatesDialog : Window
{
    public ObservableCollection<ModUpdateCandidateItem> CandidateItems { get; }

    public ModUpdatesDialog(IEnumerable<ModUpdateCandidateItem> items)
    {
        InitializeComponent();
        CandidateItems = new ObservableCollection<ModUpdateCandidateItem>(items);
        UpdatesGrid.ItemsSource = CandidateItems;
    }

    public IReadOnlyList<ModUpdateCandidateItem> GetSelectedItems() =>
        [.. CandidateItems.Where(static i => i.IsSelected)];

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

    private void OnUpdateClicked(object sender, RoutedEventArgs e)
    {
        if (!CandidateItems.Any(static i => i.IsSelected))
        {
            NotificationDialog.Show(this, "未勾選項目", "請至少勾選一個要更新的模組！", NotificationLevel.Warning);
            return;
        }
        DialogResult = true;
        Close();
    }

    private void OnCancelClicked(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }
}
