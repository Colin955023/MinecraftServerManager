using System.Runtime.CompilerServices;
using System.Windows.Input;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;

namespace MinecraftServerManager.App.Controls;

/// <summary>ListView 共用附加互動行為：點選外部取消選取、右鍵選取該列、雙擊／Enter 執行及 Delete 刪除</summary>
public static class ListViewBehaviors
{
    public static readonly DependencyProperty ClearOnOutsidePressProperty =
        DependencyProperty.RegisterAttached(
            "ClearOnOutsidePress",
            typeof(bool),
            typeof(ListViewBehaviors),
            new PropertyMetadata(false, OnClearOnOutsidePressChanged));

    public static readonly DependencyProperty SelectOnRightTapProperty =
        DependencyProperty.RegisterAttached(
            "SelectOnRightTap",
            typeof(bool),
            typeof(ListViewBehaviors),
            new PropertyMetadata(false, OnSelectOnRightTapChanged));

    public static readonly DependencyProperty InvokeCommandProperty =
        DependencyProperty.RegisterAttached(
            "InvokeCommand",
            typeof(ICommand),
            typeof(ListViewBehaviors),
            new PropertyMetadata(null, OnKeyCommandChanged));

    public static readonly DependencyProperty DeleteCommandProperty =
        DependencyProperty.RegisterAttached(
            "DeleteCommand",
            typeof(ICommand),
            typeof(ListViewBehaviors),
            new PropertyMetadata(null, OnKeyCommandChanged));

    private static readonly ConditionalWeakTable<ListView, Registration> Registrations = [];

    public static bool GetClearOnOutsidePress(DependencyObject obj) => (bool)obj.GetValue(ClearOnOutsidePressProperty);
    public static void SetClearOnOutsidePress(DependencyObject obj, bool value) => obj.SetValue(ClearOnOutsidePressProperty, value);

    public static bool GetSelectOnRightTap(DependencyObject obj) => (bool)obj.GetValue(SelectOnRightTapProperty);
    public static void SetSelectOnRightTap(DependencyObject obj, bool value) => obj.SetValue(SelectOnRightTapProperty, value);

    public static ICommand? GetInvokeCommand(DependencyObject obj) => (ICommand?)obj.GetValue(InvokeCommandProperty);
    public static void SetInvokeCommand(DependencyObject obj, ICommand? value) => obj.SetValue(InvokeCommandProperty, value);

    public static ICommand? GetDeleteCommand(DependencyObject obj) => (ICommand?)obj.GetValue(DeleteCommandProperty);
    public static void SetDeleteCommand(DependencyObject obj, ICommand? value) => obj.SetValue(DeleteCommandProperty, value);

    /// <summary>點選目標是否為會自行處理點選的互動控制項（ScrollBar 屬 RangeBase）</summary>
    internal static bool IsInteractive(DependencyObject element) =>
        element is ButtonBase or TextBox or PasswordBox or RichEditBox or AutoSuggestBox or ComboBox
            or RangeBase or Thumb or ToggleSwitch or SelectorBarItem or NavigationViewItem or NumberBox or SortableTableHeader;

    /// <summary>事件來源位於指定清單列內（不含列內互動控制項）</summary>
    public static bool IsFromItem(RoutedEventArgs e, ListView? listView = null) =>
        FindItemContainer(e.OriginalSource as DependencyObject, listView) is not null;

    private static void OnClearOnOutsidePressChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not ListView listView)
        {
            return;
        }

        listView.Loaded -= OnListViewLoaded;
        listView.Unloaded -= OnListViewUnloaded;
        DetachOutsidePress(listView);
        if (e.NewValue is true)
        {
            listView.Loaded += OnListViewLoaded;
            listView.Unloaded += OnListViewUnloaded;
            if (listView.IsLoaded)
            {
                AttachOutsidePress(listView);
            }
        }
    }

    private static void OnListViewLoaded(object sender, RoutedEventArgs e) => AttachOutsidePress((ListView)sender);

    private static void OnListViewUnloaded(object sender, RoutedEventArgs e) => DetachOutsidePress((ListView)sender);

    private static void AttachOutsidePress(ListView listView)
    {
        DetachOutsidePress(listView);

        UIElement root = listView.FindVisualRoot();
        var weakList = new WeakReference<ListView>(listView);
        var handler = new PointerEventHandler((_, args) =>
        {
            if (weakList.TryGetTarget(out ListView? target))
            {
                OnRootPointerPressed(target, args);
            }
        });
        root.AddHandler(UIElement.PointerPressedEvent, handler, handledEventsToo: true);
        Registrations.AddOrUpdate(listView, new Registration(root, handler));
    }

    private static void DetachOutsidePress(ListView listView)
    {
        if (Registrations.TryGetValue(listView, out Registration? registration))
        {
            registration.Root.RemoveHandler(UIElement.PointerPressedEvent, registration.Handler);
            Registrations.Remove(listView);
        }
    }

    private static void OnRootPointerPressed(ListView listView, PointerRoutedEventArgs e)
    {
        if (listView.SelectionMode == ListViewSelectionMode.None || listView.SelectedItems.Count == 0)
        {
            return;
        }

        for (var current = e.OriginalSource as DependencyObject; current is not null; current = VisualTreeHelper.GetParent(current))
        {
            if (IsInteractive(current))
            {
                return;
            }

            if (current is ListViewItem item && ReferenceEquals(ItemsControl.ItemsControlFromItemContainer(item), listView))
            {
                return;
            }
        }

        if (listView.SelectionMode is ListViewSelectionMode.Multiple or ListViewSelectionMode.Extended)
        {
            listView.SelectedItems.Clear();
        }
        else
        {
            listView.SelectedIndex = -1;
        }
    }

    private static void OnSelectOnRightTapChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not ListView listView)
        {
            return;
        }

        listView.RightTapped -= OnRightTapped;
        if (e.NewValue is true)
        {
            listView.RightTapped += OnRightTapped;
        }
    }

    private static void OnKeyCommandChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not ListView listView)
        {
            return;
        }

        listView.DoubleTapped -= OnDoubleTapped;
        listView.PreviewKeyDown -= OnKeyDown;
        if (GetInvokeCommand(listView) is not null || GetDeleteCommand(listView) is not null)
        {
            listView.DoubleTapped += OnDoubleTapped;
            listView.PreviewKeyDown += OnKeyDown;
        }
    }

    private static void OnDoubleTapped(object sender, DoubleTappedRoutedEventArgs e)
    {
        var listView = (ListView)sender;
        if (IsFromItem(e, listView) && TryInvoke(listView, GetInvokeCommand(listView)))
        {
            e.Handled = true;
        }
    }

    private static void OnKeyDown(object sender, KeyRoutedEventArgs e)
    {
        var listView = (ListView)sender;
        ICommand? command = e.Key switch
        {
            Windows.System.VirtualKey.Enter => GetInvokeCommand(listView),
            Windows.System.VirtualKey.Delete => GetDeleteCommand(listView),
            _ => null,
        };
        if (command is not null && IsFromItem(e, listView) && TryInvoke(listView, command))
        {
            e.Handled = true;
        }
    }

    /// <summary>延後至輸入處理完成後執行，避免在指標／按鍵事件中開啟視窗</summary>
    private static bool TryInvoke(ListView listView, ICommand? command)
    {
        if (command?.CanExecute(null) != true)
        {
            return false;
        }

        listView.DispatcherQueue.TryEnqueue(DispatcherQueuePriority.Low, () => command.TryExecute());
        return true;
    }

    private static void OnRightTapped(object sender, RightTappedRoutedEventArgs e)
    {
        var listView = (ListView)sender;
        if (FindItemContainer(e.OriginalSource as DependencyObject, listView) is not { } container)
        {
            return;
        }

        object item = listView.ItemFromContainer(container);
        if (listView.SelectionMode is ListViewSelectionMode.Multiple or ListViewSelectionMode.Extended)
        {
            if (!listView.SelectedItems.Contains(item))
            {
                listView.SelectedItems.Clear();
                listView.SelectedItems.Add(item);
            }
        }
        else
        {
            listView.SelectedItem = item;
        }
    }

    private static ListViewItem? FindItemContainer(DependencyObject? element, ListView? listView = null)
    {
        for (; element is not null; element = VisualTreeHelper.GetParent(element))
        {
            if (element is ListViewItem item)
            {
                if (listView is not null && ItemsControl.ItemsControlFromItemContainer(item) != listView)
                {
                    return null;
                }

                return item;
            }

            if (IsInteractive(element))
            {
                return null;
            }
        }

        return null;
    }

    private sealed record Registration(UIElement Root, PointerEventHandler Handler);
}
