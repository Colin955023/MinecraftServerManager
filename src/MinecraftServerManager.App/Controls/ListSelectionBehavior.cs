using System.Runtime.CompilerServices;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 清單附加行為：點選清單以外的非互動區域（或清單內空白處）時自動取消選取。
/// 以指標按下事件判斷而非失去焦點，避免按下工具列按鈕、開啟右鍵選單或對話方塊時選取被先清除。
/// </summary>
public static class ListSelectionBehavior
{
    public static readonly DependencyProperty ClearOnOutsidePressProperty =
        DependencyProperty.RegisterAttached(
            "ClearOnOutsidePress",
            typeof(bool),
            typeof(ListSelectionBehavior),
            new PropertyMetadata(false, OnClearOnOutsidePressChanged));

    private static readonly ConditionalWeakTable<ListView, Registration> Registrations = [];

    public static bool GetClearOnOutsidePress(DependencyObject obj) =>
        (bool)obj.GetValue(ClearOnOutsidePressProperty);

    public static void SetClearOnOutsidePress(DependencyObject obj, bool value) =>
        obj.SetValue(ClearOnOutsidePressProperty, value);

    /// <summary>判斷點選目標是否為會自行處理點選的互動控制項（按下時不應取消清單選取）</summary>
    internal static bool IsInteractive(DependencyObject element) =>
        element is ButtonBase or TextBox or PasswordBox or RichEditBox or AutoSuggestBox or ComboBox
            or RangeBase or Thumb or ToggleSwitch or SelectorBarItem or NumberBox or SortableTableHeader;

    private static void OnClearOnOutsidePressChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not ListView listView)
        {
            return;
        }

        listView.Loaded -= OnListViewLoaded;
        listView.Unloaded -= OnListViewUnloaded;
        Detach(listView);
        if (e.NewValue is true)
        {
            listView.Loaded += OnListViewLoaded;
            listView.Unloaded += OnListViewUnloaded;
            if (listView.IsLoaded)
            {
                Attach(listView);
            }
        }
    }

    private static void OnListViewLoaded(object sender, RoutedEventArgs e) => Attach((ListView)sender);

    private static void OnListViewUnloaded(object sender, RoutedEventArgs e) => Detach((ListView)sender);

    private static void Attach(ListView listView)
    {
        Detach(listView);

        // 掛在最上層視覺根（頁面、對話方塊或視窗內容），才能收到清單以外區域的點選
        UIElement root = listView;
        while (VisualTreeHelper.GetParent(root) is UIElement parent)
        {
            root = parent;
        }

        var handler = new PointerEventHandler((_, args) => OnPointerPressed(listView, args));
        root.AddHandler(UIElement.PointerPressedEvent, handler, handledEventsToo: true);
        Registrations.AddOrUpdate(listView, new Registration(root, handler));
    }

    private static void Detach(ListView listView)
    {
        if (Registrations.TryGetValue(listView, out Registration? registration))
        {
            registration.Root.RemoveHandler(UIElement.PointerPressedEvent, registration.Handler);
            Registrations.Remove(listView);
        }
    }

    private static void OnPointerPressed(ListView listView, PointerRoutedEventArgs e)
    {
        if (listView.SelectionMode == ListViewSelectionMode.None || listView.SelectedItems.Count == 0)
        {
            return;
        }

        var current = e.OriginalSource as DependencyObject;
        while (current is not null)
        {
            if (IsInteractive(current))
            {
                return;
            }

            if (current is ListViewItem item && ReferenceEquals(ItemsControl.ItemsControlFromItemContainer(item), listView))
            {
                return;
            }

            current = VisualTreeHelper.GetParent(current);
        }

        listView.SelectedIndex = -1;
    }

    private sealed record Registration(UIElement Root, PointerEventHandler Handler);
}
