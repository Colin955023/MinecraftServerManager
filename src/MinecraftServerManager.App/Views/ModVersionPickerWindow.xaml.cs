using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>模組版本選擇視窗</summary>
public sealed partial class ModVersionPickerWindow : Window
{
    public ModVersionPickerWindow(ModVersionPickerViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.AttachDialog(this, $"選擇模組版本 - {viewModel.ProjectTitle}", 820, 560, Bindings.StopTracking, ViewModel, sortTargets: HeaderSort);
    }

    public ModVersionPickerViewModel ViewModel { get; }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<ModVersionDisplayItem>(() => ViewModel.Versions, TableSortKeys.ModVersions);
}
