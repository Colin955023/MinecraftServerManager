using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;

namespace MinecraftServerManager.App.Behaviors;

/// <summary>
/// 提供 DataGrid 欄位標頭雙擊自動最適欄寬之附加行為
/// </summary>
public static class DataGridHeaderAutoFitBehavior
{
    private static bool _handlerRegistered;

    public static readonly DependencyProperty EnableHeaderDoubleClickAutoFitProperty =
        DependencyProperty.RegisterAttached(
            "EnableHeaderDoubleClickAutoFit",
            typeof(bool),
            typeof(DataGridHeaderAutoFitBehavior),
            new PropertyMetadata(false, OnEnableChanged));

    public static bool GetEnableHeaderDoubleClickAutoFit(DependencyObject obj) =>
        (bool)obj.GetValue(EnableHeaderDoubleClickAutoFitProperty);

    public static void SetEnableHeaderDoubleClickAutoFit(DependencyObject obj, bool value) =>
        obj.SetValue(EnableHeaderDoubleClickAutoFitProperty, value);

    private static void OnEnableChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if ((bool)e.NewValue && !_handlerRegistered)
        {
            _handlerRegistered = true;
            EventManager.RegisterClassHandler(
                typeof(DataGridColumnHeader),
                Control.MouseDoubleClickEvent,
                new MouseButtonEventHandler(OnHeaderMouseDoubleClick));
        }
    }

    private static void OnHeaderMouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (sender is DataGridColumnHeader header && header.Column is not null)
        {
            // 將欄位寬度切換為 Auto，自動調整為最寬項目寬度
            header.Column.Width = 0;
            header.Column.Width = DataGridLength.Auto;
            e.Handled = true;
        }
    }
}
