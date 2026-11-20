using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>模組版本選擇視窗</summary>
public sealed partial class ModVersionPickerDialog : Window
{
    public ModVersionPickerViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public ModVersionPickerDialog(ModVersionPickerViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, $"選擇模組版本 - {viewModel.ProjectTitle}", 820, 560, Bindings.StopTracking);

        ViewModel.RequestClose += ModalWindowHost.CloseWithResult(this, success => DialogResult = success);
    }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<ModVersionDisplayItem>(() => ViewModel.Versions, TableSortKeys.ModVersions);
}
