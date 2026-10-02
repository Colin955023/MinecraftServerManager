using System.Collections.Specialized;
using System.Windows;
using System.Windows.Input;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public partial class ServerMonitorWindow : Window
{
    private readonly ServerMonitorViewModel _viewModel;

    public ServerMonitorWindow(ServerMonitorViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = _viewModel;

        if (Icon == null)
        {
            try
            {
                Icon = System.Windows.Media.Imaging.BitmapFrame.Create(
                    new Uri("pack://application:,,,/MinecraftServerManager.App;component/assets/icon.ico", UriKind.RelativeOrAbsolute));
            }
            catch
            {
            }
        }

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
        if (_viewModel.IsAutoScrollEnabled && e.Action == NotifyCollectionChangedAction.Add && LogListBox.Items.Count > 0)
        {
            Dispatcher.BeginInvoke(System.Windows.Threading.DispatcherPriority.Loaded, () =>
            {
                var sv = GetLogScrollViewer();
                if (sv != null)
                {
                    sv.ScrollToBottom();
                }
                else
                {
                    LogListBox.ScrollIntoView(LogListBox.Items[^1]);
                }
            });
        }
    }

    private void CommandInputBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            if (_viewModel.SendCommandCommand.CanExecute(null))
            {
                _viewModel.SendCommandCommand.Execute(null);
                if (_viewModel.IsAutoScrollEnabled)
                {
                    Dispatcher.BeginInvoke(System.Windows.Threading.DispatcherPriority.Loaded, () =>
                    {
                        GetLogScrollViewer()?.ScrollToBottom();
                    });
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
