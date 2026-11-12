using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>管理伺服器頁面 View</summary>
public sealed partial class ManageServerView : UserControl
{
    public ManageServerViewModel ViewModel { get; }

    public ManageServerView(ManageServerViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
    }

    private void OnServersListViewDoubleTapped(object sender, DoubleTappedRoutedEventArgs e)
    {
        DispatcherQueue.TryEnqueue(DispatcherQueuePriority.Low, () =>
        {
            if (ViewModel.Lifecycle.MonitorServerCommand.CanExecute(null))
            {
                ViewModel.Lifecycle.MonitorServerCommand.Execute(null);
            }
        });
    }

    private void OnHeaderSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.List.Servers.SortBy(TableSortKeys.Servers, e);

    private void OnHeaderAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.List.Servers, TableSortKeys.Servers);
}
