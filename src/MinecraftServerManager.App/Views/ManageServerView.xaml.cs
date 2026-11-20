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
        DeleteServerAccelerator.ScopeOwner = ServersListView;
    }

    private void OnServersListViewDoubleTapped(object sender, DoubleTappedRoutedEventArgs e) => OpenMonitorDeferred();

    private void OpenMonitorDeferred()
    {
        DispatcherQueue.TryEnqueue(DispatcherQueuePriority.Low, () =>
        {
            ViewModel.Lifecycle.MonitorServerCommand.TryExecute();
        });
    }

    private void OnServersListViewKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
        {
            e.Handled = true;
            OpenMonitorDeferred();
        }
    }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<ServerRowItem>(() => ViewModel.List.Servers, TableSortKeys.Servers);
}
