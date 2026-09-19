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

    private void OnLogsCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (_viewModel.IsAutoScrollEnabled && LogListBox.Items.Count > 0)
        {
            LogListBox.ScrollIntoView(LogListBox.Items[^1]);
        }
    }

    private void CommandInputBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            if (_viewModel.SendCommandCommand.CanExecute(null))
            {
                _viewModel.SendCommandCommand.Execute(null);
            }
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
