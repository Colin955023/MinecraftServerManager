using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>模組更新視窗</summary>
public sealed partial class ModUpdatesWindow : Window
{
    public ModUpdatesWindow(ModUpdateSelectionViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.AttachDialog(this, "發現模組更新", 800, 540, Bindings.StopTracking, ViewModel, sortTargets: HeaderSort);
    }

    public ModUpdateSelectionViewModel ViewModel { get; }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<ModUpdateCandidateItem>(() => ViewModel.CandidateItems, TableSortKeys.UpdateCandidates);
}
