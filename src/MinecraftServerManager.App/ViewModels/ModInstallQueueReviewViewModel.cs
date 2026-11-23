using System.Collections.ObjectModel;
using System.Collections.Specialized;
using CommunityToolkit.Mvvm.Input;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>待安裝模組清單視窗：佇列為空時停用清空與開始安裝</summary>
public sealed partial class ModInstallQueueReviewViewModel : DialogViewModelBase
{
    public ModInstallQueueReviewViewModel(ObservableCollection<ModInstallQueueItem> queue)
    {
        ArgumentNullException.ThrowIfNull(queue);
        Queue = queue;
        Queue.CollectionChanged += OnQueueChanged;
    }

    public ObservableCollection<ModInstallQueueItem> Queue { get; }

    public bool HasItems => Queue.Count > 0;

    [RelayCommand(CanExecute = nameof(HasItems))]
    public void ClearQueue() => Queue.Clear();

    [RelayCommand(CanExecute = nameof(HasItems))]
    public void StartInstall() => Close(true);

    [RelayCommand]
    public void Close() => Close(false);

    private void OnQueueChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        ClearQueueCommand.NotifyCanExecuteChanged();
        StartInstallCommand.NotifyCanExecuteChanged();
    }

    protected override void OnDispose() => Queue.CollectionChanged -= OnQueueChanged;
}
