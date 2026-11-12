using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>模組版本選擇對話方塊（原生模態視窗，透過 ModalWindowHost 裝載）</summary>
public sealed partial class ModVersionPickerDialog : Window
{
    public ModVersionPickerViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public ModVersionPickerDialog(ModVersionPickerViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, "選擇模組版本", 820, 560, Bindings.StopTracking);

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            ModalWindowHost.CloseDeferred(this);
        };
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.Versions.SortBy(TableSortKeys.ModVersions, e);

    private void OnHeaderAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.Versions, TableSortKeys.ModVersions);
}
