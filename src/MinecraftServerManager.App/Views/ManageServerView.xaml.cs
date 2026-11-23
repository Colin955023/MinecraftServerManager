using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>管理伺服器頁面 View</summary>
public sealed partial class ManageServerView : UserControl
{
    public ManageServerView(ManageServerViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        DeleteServerAccelerator.ScopeOwner = ServersListView;
    }

    public ManageServerViewModel ViewModel { get; }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<ServerRowItem>(() => ViewModel.List.Servers, TableSortKeys.Servers);
}
