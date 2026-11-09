using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 為 ComboBox 提供滑鼠滾輪快速切換選項之附加屬性
/// </summary>
public static class ComboBoxScrollHelper
{
    public static readonly DependencyProperty EnableWheelScrollProperty =
        DependencyProperty.RegisterAttached(
            "EnableWheelScroll",
            typeof(bool),
            typeof(ComboBoxScrollHelper),
            new PropertyMetadata(false, OnEnableWheelScrollChanged));

    public static bool GetEnableWheelScroll(DependencyObject obj) =>
        (bool)obj.GetValue(EnableWheelScrollProperty);

    public static void SetEnableWheelScroll(DependencyObject obj, bool value) =>
        obj.SetValue(EnableWheelScrollProperty, value);

    private static void OnEnableWheelScrollChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is ComboBox comboBox)
        {
            comboBox.PointerWheelChanged -= OnPointerWheelChanged;
            if (e.NewValue is true)
            {
                comboBox.PointerWheelChanged += OnPointerWheelChanged;
            }
        }
    }

    private static void OnPointerWheelChanged(object sender, PointerRoutedEventArgs e)
    {
        if (sender is not ComboBox comboBox)
        {
            return;
        }

        if (comboBox.IsDropDownOpen)
        {
            return;
        }

        int count = comboBox.Items.Count;
        if (count <= 1 || !comboBox.IsEnabled)
        {
            return;
        }

        var properties = e.GetCurrentPoint(comboBox).Properties;
        int delta = properties.MouseWheelDelta;

        if (delta > 0)
        {
            if (comboBox.SelectedIndex > 0)
            {
                comboBox.SelectedIndex--;
                e.Handled = true;
            }
        }
        else if (delta < 0)
        {
            if (comboBox.SelectedIndex < count - 1)
            {
                comboBox.SelectedIndex++;
                e.Handled = true;
            }
        }
    }
}
