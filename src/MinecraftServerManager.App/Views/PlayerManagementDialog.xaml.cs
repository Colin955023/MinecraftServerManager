using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器名單管理視窗</summary>
public sealed partial class PlayerManagementDialog : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(PlayerManagementDialog));

    public PlayerManagementViewModel ViewModel { get; }
    public bool? DialogResult { get; private set; }

    public PlayerManagementDialog(PlayerManagementViewModel viewModel)
    {
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.ConfigureDialogWindow(this, "伺服器名單管理", 1060, 740, Bindings.StopTracking);

        if (Content is FrameworkElement fe)
        {
            fe.Loaded += async (_, _) =>
            {
                try
                {
                    await ViewModel.InitializeAsync().ConfigureAwait(true);
                }
                catch (Exception ex)
                {
                    Logger.Error(ex, "初始化名單管理失敗");
                }
            };
        }

        ViewModel.RequestClose += ModalWindowHost.CloseWithResult(this, success => DialogResult = success);

        ModalWindowHost.RegisterUnsavedChangesPrompt(
            this,
            () => DialogResult is null && ViewModel.HasUnsavedChanges,
            ViewModel.ConfirmDiscardAsync,
            () => DialogResult = false,
            Logger);
    }

    private void RemoveWhitelist_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerWhitelistEntry entry })
        {
            ViewModel.RemoveWhitelist(entry);
        }
    }

    private void RemoveBannedPlayer_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerBannedPlayerEntry entry })
        {
            ViewModel.RemoveBannedPlayer(entry);
        }
    }

    private void RemoveBannedIp_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: ServerBannedIpEntry entry })
        {
            ViewModel.RemoveBannedIp(entry);
        }
    }

    public ITableSortTarget OperatorSort => field ??= new TableSortTarget<OperatorRowItem>(() => ViewModel.OperatorRows, TableSortKeys.Operators);

    public ITableSortTarget WhitelistSort => field ??= new TableSortTarget<ServerWhitelistEntry>(() => ViewModel.Whitelist, TableSortKeys.Whitelist);

    public ITableSortTarget BannedPlayerSort => field ??= new TableSortTarget<ServerBannedPlayerEntry>(() => ViewModel.BannedPlayers, TableSortKeys.BannedPlayers);

    public ITableSortTarget BannedIpSort => field ??= new TableSortTarget<ServerBannedIpEntry>(() => ViewModel.BannedIps, TableSortKeys.BannedIps);
}
