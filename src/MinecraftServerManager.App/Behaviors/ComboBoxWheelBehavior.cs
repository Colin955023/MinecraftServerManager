using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace MinecraftServerManager.App.Behaviors;

/// <summary>
/// 提供 ComboBox 滑鼠懸停滾輪切換選項的附加行為
/// </summary>
public static class ComboBoxWheelBehavior
{
    public static readonly DependencyProperty EnableWheelSelectionProperty =
        DependencyProperty.RegisterAttached(
            "EnableWheelSelection",
            typeof(bool),
            typeof(ComboBoxWheelBehavior),
            new PropertyMetadata(false, OnEnableWheelSelectionChanged));

    public static bool GetEnableWheelSelection(DependencyObject obj) =>
        (bool)obj.GetValue(EnableWheelSelectionProperty);

    public static void SetEnableWheelSelection(DependencyObject obj, bool value) =>
        obj.SetValue(EnableWheelSelectionProperty, value);

    private static void OnEnableWheelSelectionChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is ComboBox comboBox)
        {
            comboBox.PreviewMouseWheel -= ComboBox_PreviewMouseWheel;
            if ((bool)e.NewValue)
            {
                comboBox.PreviewMouseWheel += ComboBox_PreviewMouseWheel;
            }
        }
    }

    private static void ComboBox_PreviewMouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (sender is not ComboBox comboBox || !comboBox.IsEnabled || comboBox.Items.Count == 0)
        {
            return;
        }

        // 若下拉選單已展開，維持預設滾動清單行為
        if (comboBox.IsDropDownOpen)
        {
            return;
        }

        int currentIndex = comboBox.SelectedIndex;
        if (e.Delta < 0)
        {
            // 向下滾動 -> 選取下一個
            if (currentIndex < comboBox.Items.Count - 1)
            {
                comboBox.SelectedIndex = currentIndex + 1;
                e.Handled = true;
            }
        }
        else if (e.Delta > 0)
        {
            // 向上滾動 -> 選取上一個
            if (currentIndex > 0)
            {
                comboBox.SelectedIndex = currentIndex - 1;
                e.Handled = true;
            }
        }
    }
}
