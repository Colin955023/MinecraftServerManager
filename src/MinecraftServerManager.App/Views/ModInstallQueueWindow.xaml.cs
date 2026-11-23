using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>待安裝模組清單視窗</summary>
public sealed partial class ModInstallQueueWindow : Window
{
    public ModInstallQueueWindow(ModInstallQueueReviewViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.AttachDialog(this, "待安裝模組清單", 800, 540, Bindings.StopTracking, ViewModel, sortTargets: HeaderSort);
    }

    public ModInstallQueueReviewViewModel ViewModel { get; }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<ModInstallQueueItem>(() => ViewModel.Queue, TableSortKeys.InstallQueue);
}
