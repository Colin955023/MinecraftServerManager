using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器名單管理視窗（原生模態視窗，透過 ModalWindowHost 裝載）</summary>
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

        ViewModel.RequestClose += success =>
        {
            DialogResult = success;
            ModalWindowHost.CloseDeferred(this);
        };

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

    private void OnOperatorSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.OperatorRows.SortBy(TableSortKeys.Operators, e);

    private void OnOperatorAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.OperatorRows, TableSortKeys.Operators);

    private void OnWhitelistSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.Whitelist.SortBy(TableSortKeys.Whitelist, e);

    private void OnWhitelistAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.Whitelist, TableSortKeys.Whitelist);

    private void OnBannedPlayerSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.BannedPlayers.SortBy(TableSortKeys.BannedPlayers, e);

    private void OnBannedPlayerAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.BannedPlayers, TableSortKeys.BannedPlayers);

    private void OnBannedIpSortRequested(object? sender, SortRequestedEventArgs e) => ViewModel.BannedIps.SortBy(TableSortKeys.BannedIps, e);

    private void OnBannedIpAutoFitRequested(object? sender, string propertyName) => ((SortableTableHeader)sender!).AutoFit(ViewModel.BannedIps, TableSortKeys.BannedIps);
}
