using System.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組更新視窗：勾選要更新的模組，未勾選任何項目時停用更新</summary>
public sealed partial class ModUpdateSelectionViewModel : DialogViewModelBase
{
    public ModUpdateSelectionViewModel(IEnumerable<ModUpdateCandidateItem> items)
    {
        ArgumentNullException.ThrowIfNull(items);
        CandidateItems = new BulkObservableCollection<ModUpdateCandidateItem>(items);
        foreach (var item in CandidateItems)
        {
            item.PropertyChanged += OnItemPropertyChanged;
        }
    }

    public BulkObservableCollection<ModUpdateCandidateItem> CandidateItems { get; }

    public bool HasSelection => CandidateItems.Any(static i => i.IsSelected);

    public IReadOnlyList<ModUpdateCandidateItem> GetSelectedItems() =>
        (ModUpdateCandidateItem[])[.. CandidateItems.Where(static i => i.IsSelected)];

    [RelayCommand]
    public void SelectAll() => SetAllSelected(true);

    [RelayCommand]
    public void DeselectAll() => SetAllSelected(false);

    [RelayCommand(CanExecute = nameof(HasSelection))]
    public void Confirm() => Close(true);

    [RelayCommand]
    public void Cancel() => Close(false);

    private void SetAllSelected(bool selected)
    {
        foreach (var item in CandidateItems)
        {
            item.IsSelected = selected;
        }
    }

    private void OnItemPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(ModUpdateCandidateItem.IsSelected))
        {
            ConfirmCommand.NotifyCanExecuteChanged();
        }
    }

    protected override void OnDispose()
    {
        foreach (var item in CandidateItems)
        {
            item.PropertyChanged -= OnItemPropertyChanged;
        }
    }
}
