using System.Collections.Specialized;
using System.Windows;
using System.Windows.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ServerMonitorWindow : Window
{
    private readonly ServerMonitorViewModel _viewModel;
    private readonly IUiService _ui;
    private bool _scrollQueued;

    public ServerMonitorWindow(ServerMonitorViewModel viewModel, IUiService ui)
    {
        ArgumentNullException.ThrowIfNull(ui);
        InitializeComponent();
        _viewModel = viewModel;
        _ui = ui;
        DataContext = _viewModel;

        if (_viewModel.Logs is INotifyCollectionChanged notify)
        {
            notify.CollectionChanged += OnLogsCollectionChanged;
        }

        Closed += ServerMonitorWindow_Closed;
    }

    private System.Windows.Controls.ScrollViewer? _logScrollViewer;

    private System.Windows.Controls.ScrollViewer? GetLogScrollViewer()
    {
        if (_logScrollViewer != null)
        {
            return _logScrollViewer;
        }

        if (System.Windows.Media.VisualTreeHelper.GetChildrenCount(LogListBox) > 0)
        {
            var border = System.Windows.Media.VisualTreeHelper.GetChild(LogListBox, 0) as System.Windows.Controls.Decorator;
            _logScrollViewer = border?.Child as System.Windows.Controls.ScrollViewer;
        }
        return _logScrollViewer;
    }

    private void OnLogsCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (_viewModel.IsAutoScrollEnabled &&
            e.Action is NotifyCollectionChangedAction.Add or NotifyCollectionChangedAction.Reset &&
            LogListBox.Items.Count > 0 &&
            !_scrollQueued)
        {
            _scrollQueued = true;
            _ui.PostToUi(() =>
            {
                _scrollQueued = false;
                if (!_viewModel.IsAutoScrollEnabled || LogListBox.Items.Count == 0)
                {
                    return;
                }

                var sv = GetLogScrollViewer();
                if (sv != null)
                {
                    sv.ScrollToBottom();
                }
                else
                {
                    LogListBox.ScrollIntoView(LogListBox.Items[^1]);
                }
            }, afterLayout: true);
        }
    }

    private void PlayerListItem_PreviewMouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (sender is System.Windows.Controls.ListBoxItem item && item.DataContext is string playerName && !string.IsNullOrWhiteSpace(playerName))
        {
            _viewModel.CopyPlayerName(playerName);
            e.Handled = true;
        }
    }

    private void CommandInputBox_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            if (_viewModel.SendCommandCommand.CanExecute(null))
            {
                _viewModel.SendCommandCommand.Execute(null);
                if (_viewModel.IsAutoScrollEnabled)
                {
                    _ui.PostToUi(() =>
                    {
                        GetLogScrollViewer()?.ScrollToBottom();
                    }, afterLayout: true);
                }
            }
            e.Handled = true;
        }
        else if (e.Key == Key.Up)
        {
            _viewModel.NavigateHistory(previous: true);
            CommandInputBox.CaretIndex = CommandInputBox.Text.Length;
            e.Handled = true;
        }
        else if (e.Key == Key.Down)
        {
            _viewModel.NavigateHistory(previous: false);
            CommandInputBox.CaretIndex = CommandInputBox.Text.Length;
            e.Handled = true;
        }
    }

    private void ServerMonitorWindow_Closed(object? sender, EventArgs e)
    {
        if (_viewModel.Logs is INotifyCollectionChanged notify)
        {
            notify.CollectionChanged -= OnLogsCollectionChanged;
        }
        _viewModel.Dispose();
    }
}
