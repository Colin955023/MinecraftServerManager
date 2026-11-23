using System.ComponentModel;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;
using Windows.Graphics;

namespace MinecraftServerManager.App;

/// <summary>應用程式主視窗</summary>
public sealed partial class MainWindow : Window, IAsyncDisposable
{
    private const int DefaultWidthDip = 1350;
    private const int DefaultHeightDip = 820;
    private const int MaxNotifications = 4;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MainWindow));

    private readonly Dictionary<string, UIElement> _viewCache = new(StringComparer.OrdinalIgnoreCase);
    private readonly TaskCompletionSource _loadedTcs = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly CancellationTokenSource _closingCts = new();
    private AppCompositionRoot? _compositionRoot;
    private MainViewModel? _viewModel;
    private ISettingsManager? _settings;
    private WinUiService? _uiService;
    private RectInt32? _restoredBounds;
    private bool _shutdownInProgress;
    private bool _shutdownCompleted;
    private int _disposed;

    public MainWindow()
    {
        InitializeComponent();
        Title = "Minecraft 伺服器管理器";

        WindowChromeService.Apply(this, AppTitleBar);
        WindowIconHelper.SetIcon(AppWindow);

        AppWindow.Closing += OnAppWindowClosing;
        Closed += (_, _) => AppLogging.Shutdown();
        RootGrid.Loaded += OnMainWindowLoaded;
    }

    public MainViewModel? ViewModel => _viewModel;

    /// <summary>啟用前套用主題與上次的視窗位置，避免顯示後才跳動</summary>
    public void PrepareForActivation(ISettingsManager settings, WinUiService uiService)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentNullException.ThrowIfNull(uiService);
        _settings = settings;
        _uiService = uiService;
        ApplyThemeMode(settings.GetThemeMode());
        RestoreWindowPosition(settings.GetMainWindowSettings());
        AppWindow.Changed += OnAppWindowChanged;
    }

    /// <summary>等待主視窗內容載入；對話框需要有效的 XamlRoot</summary>
    public Task WaitForLoadedAsync() => _loadedTcs.Task;

    /// <summary>初始化主視窗之組合根與 ViewModel 繫結（須於 <see cref="PrepareForActivation"/> 後呼叫）</summary>
    public void InitializeViewModel(AppCompositionRoot compositionRoot)
    {
        ArgumentNullException.ThrowIfNull(compositionRoot);
        _compositionRoot = compositionRoot;
        _viewModel = compositionRoot.MainViewModel;

        _viewModel.PropertyChanged += OnViewModelPropertyChanged;
        _viewModel.ResetWindowSizeRequested += OnResetWindowSizeRequested;
        _viewModel.ThemeModeChanged += ApplyThemeMode;

        ApplyThemeMode(_viewModel.ThemeMode);
        UpdateCurrentPage(_viewModel.CurrentPage);
        PushWindowMetrics();

        _ = ViewModelBase.RunSafeAsync(() => _viewModel.CheckOrphanedServersOnStartupAsync(_closingCts.Token), "檢查遺留伺服器行程", Logger);
        _ = ViewModelBase.RunSafeAsync(() => _viewModel.CheckForUpdateOnStartupAsync(_closingCts.Token), "啟動檢查更新", Logger);
    }

    private void OnMainWindowLoaded(object sender, RoutedEventArgs e)
    {
        RootGrid.Loaded -= OnMainWindowLoaded;
        Logger.Information("主視窗 UI 已載入完成");
        _loadedTcs.TrySetResult();
    }

    private void ApplyThemeMode(string mode)
    {
        ElementTheme targetTheme = mode switch
        {
            "light" => ElementTheme.Light,
            "dark" => ElementTheme.Dark,
            _ => ElementTheme.Default
        };

        RootGrid.RequestedTheme = targetTheme;
        // 由 WinUiService 統一同步全部視窗內容與標題列
        _uiService?.CurrentTheme = targetTheme;

        Logger.Information("主視窗套用主題模式：{Mode}（{TargetTheme}）", mode, targetTheme);
    }

    private static string? GetPageKey(PageViewModel page) => page switch
    {
        CreateServerViewModel => PageKeys.Create,
        ManageServerViewModel => PageKeys.Manage,
        ModsViewModel => PageKeys.Mods,
        AboutPreferencesViewModel => PageKeys.AboutPreferences,
        _ => null
    };

    private void UpdateCurrentPage(PageViewModel? page)
    {
        if (page is null || _viewModel is null)
        {
            return;
        }

        string? key = GetPageKey(page);
        PageContentHost.Content = key is null
            ? new TextBlock { Text = page.Title, Margin = new Thickness(20) }
            : GetOrCreateView(key, page);

        // 程式設定 SelectedItem 不會觸發 ItemInvoked
        NavView.SelectedItem = NavView.MenuItems.Concat(NavView.FooterMenuItems)
            .OfType<NavigationViewItem>()
            .FirstOrDefault(item => string.Equals(item.Tag as string, key, StringComparison.Ordinal));
    }

    private UIElement GetOrCreateView(string key, PageViewModel page)
    {
        if (!_viewCache.TryGetValue(key, out var view))
        {
            view = page switch
            {
                CreateServerViewModel vm => new CreateServerView(vm),
                ManageServerViewModel vm => new ManageServerView(vm),
                ModsViewModel vm => new ModsView(vm),
                AboutPreferencesViewModel vm => new AboutPreferencesView(vm),
                _ => throw new ArgumentOutOfRangeException(nameof(page), page.GetType().Name, "未知的頁面類型")
            };
            _viewCache[key] = view;
        }

        return view;
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainViewModel.CurrentPage))
        {
            UpdateCurrentPage(_viewModel?.CurrentPage);
        }
    }

    private void OnAppWindowClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_shutdownCompleted)
        {
            return;
        }

        // 一律先攔截：確認並停止伺服器（無執行中伺服器時直接通過）、等待處置完成後才真正關閉
        args.Cancel = true;
        if (_shutdownInProgress)
        {
            return;
        }

        _shutdownInProgress = true;
        _closingCts.Cancel();
        Logger.Information("主視窗關閉請求：停止伺服器並釋放資源");
        _ = ViewModelBase.RunSafeAsync(ShutdownAndCloseAsync, "關閉應用程式與伺服器資源", Logger);
    }

    /// <summary>儲存視窗位置並退訂全部事件；頁面處置統一由組合根負責</summary>
    private async Task CompleteShutdownAsync()
    {
        await SaveWindowPositionAsync();
        _shutdownCompleted = true;
        RootGrid.Loaded -= OnMainWindowLoaded;
        AppWindow.Closing -= OnAppWindowClosing;
        AppWindow.Changed -= OnAppWindowChanged;
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
            _viewModel.ResetWindowSizeRequested -= OnResetWindowSizeRequested;
            _viewModel.ThemeModeChanged -= ApplyThemeMode;
        }
    }

    private async Task ShutdownAndCloseAsync()
    {
        try
        {
            bool proceed = _compositionRoot is null || await _compositionRoot.StopAllServersForShutdownAsync();
            if (!proceed)
            {
                Logger.Information("使用者取消關閉應用程式");
                return;
            }

            await CompleteShutdownAsync();
            try
            {
                await DisposeAsync();
            }
            catch (OperationCanceledException)
            {
                Logger.Information("關閉應用程式資源作業已取消");
            }
            catch (Exception ex)
            {
                Logger.Warning(ex, "關閉應用程式資源時發生例外");
            }

            DispatcherQueue.TryEnqueue(Close);
        }
        finally
        {
            // 僅於取消或失敗（尚未完成收尾）時允許再次關閉
            _shutdownInProgress = _shutdownCompleted;
        }
    }

    /// <summary>冪等釋放組合根</summary>
    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        try
        {
            if (_compositionRoot is not null)
            {
                await _compositionRoot.DisposeAsync().ConfigureAwait(false);
            }
        }
        finally
        {
            _closingCts.Dispose();
        }
    }

    private void OnNavItemInvoked(NavigationView sender, NavigationViewItemInvokedEventArgs args)
    {
        switch (args.InvokedItemContainer?.Tag as string)
        {
            case PageKeys.Import:
                _viewModel?.ImportServerCommand.TryExecute();
                break;
            case PageKeys.OpenFolder:
                _viewModel?.OpenServersFolderCommand.TryExecute();
                break;
            case { } pageKey:
                _viewModel?.Navigate(pageKey);
                break;
        }
    }
}
