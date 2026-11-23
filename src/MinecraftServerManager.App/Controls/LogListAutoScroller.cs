using System.Collections.Specialized;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Controls;

/// <summary>日誌清單自動捲動：集合新增或重設後，於版面配置完成時捲到最底（合併同批次多次通知）</summary>
public sealed partial class LogListAutoScroller : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LogListAutoScroller));

    private readonly ListView _listView;
    private readonly BulkObservableCollection<string> _items;
    private readonly IUiService _ui;
    private readonly Func<bool> _isEnabled;
    private ScrollViewer? _scrollViewer;
    private bool _queued;
    private bool _disposed;

    /// <summary>監看 <paramref name="items"/> 變更並捲動 <paramref name="listView"/>；<paramref name="isEnabled"/> 回傳 false 時暫停</summary>
    public LogListAutoScroller(ListView listView, BulkObservableCollection<string> items, IUiService ui, Func<bool>? isEnabled = null)
    {
        ArgumentNullException.ThrowIfNull(listView);
        ArgumentNullException.ThrowIfNull(items);
        ArgumentNullException.ThrowIfNull(ui);
        _listView = listView;
        _items = items;
        _ui = ui;
        _isEnabled = isEnabled ?? (static () => true);
        _items.CollectionChanged += OnCollectionChanged;
    }

    private void OnCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (_queued || !_isEnabled() || _items.Count == 0 ||
            e.Action is not (NotifyCollectionChangedAction.Add or NotifyCollectionChangedAction.Reset))
        {
            return;
        }

        _queued = true;
        _ui.PostToUi(ScrollToEnd, afterLayout: true);
    }

    private void ScrollToEnd()
    {
        _queued = false;
        if (_disposed || !_isEnabled() || _items.Count == 0)
        {
            return;
        }

        try
        {
            // ScrollIntoView(字串) 會定位到第一個相同字串而造成跳動，優先直接捲動內部 ScrollViewer
            _scrollViewer ??= _listView.FindDescendant<ScrollViewer>();
            if (_scrollViewer is not null)
            {
                _scrollViewer.ChangeView(null, _scrollViewer.ScrollableHeight, null, disableAnimation: true);
            }
            else
            {
                _listView.ScrollIntoView(_items[^1]);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "日誌自動捲動失敗");
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _scrollViewer = null;
        _items.CollectionChanged -= OnCollectionChanged;
    }
}
