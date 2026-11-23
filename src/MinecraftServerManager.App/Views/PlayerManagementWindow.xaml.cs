using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器名單管理視窗</summary>
public sealed partial class PlayerManagementWindow : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(PlayerManagementWindow));

    public PlayerManagementWindow(PlayerManagementViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.AttachDialog(
            this,
            "伺服器名單管理",
            1060,
            740,
            Bindings.StopTracking,
            ViewModel,
            Logger,
            sortTargets: [OperatorSort, WhitelistSort, BannedPlayerSort, BannedIpSort]);
        ModalWindowHost.RunOnLoadedOnce(this, ViewModel.InitializeAsync, Logger, "初始化名單管理");
    }

    public PlayerManagementViewModel ViewModel { get; }

    public ITableSortTarget OperatorSort => field ??= new TableSortTarget<OperatorRowItem>(() => ViewModel.OperatorRows, TableSortKeys.Operators);

    public ITableSortTarget WhitelistSort => field ??= new TableSortTarget<ServerWhitelistEntry>(() => ViewModel.Whitelist, TableSortKeys.Whitelist);

    public ITableSortTarget BannedPlayerSort => field ??= new TableSortTarget<ServerBannedPlayerEntry>(() => ViewModel.BannedPlayers, TableSortKeys.BannedPlayers);

    public ITableSortTarget BannedIpSort => field ??= new TableSortTarget<ServerBannedIpEntry>(() => ViewModel.BannedIps, TableSortKeys.BannedIps);

    private void OnRemoveWhitelistClicked(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerWhitelistEntry entry })
        {
            ViewModel.RemoveWhitelist(entry);
        }
    }

    private void OnRemoveBannedPlayerClicked(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerBannedPlayerEntry entry })
        {
            ViewModel.RemoveBannedPlayer(entry);
        }
    }

    private void OnRemoveBannedIpClicked(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerBannedIpEntry entry })
        {
            ViewModel.RemoveBannedIp(entry);
        }
    }

}
