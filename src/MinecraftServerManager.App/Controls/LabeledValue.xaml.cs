using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.UI.Text;

namespace MinecraftServerManager.App.Controls;

/// <summary>「標籤：值」單行文字，過長截斷</summary>
public sealed partial class LabeledValue : UserControl
{
    public static readonly DependencyProperty LabelProperty =
        DependencyProperty.Register(nameof(Label), typeof(string), typeof(LabeledValue), new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty ValueProperty =
        DependencyProperty.Register(nameof(Value), typeof(string), typeof(LabeledValue), new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty ValueWeightProperty =
        DependencyProperty.Register(nameof(ValueWeight), typeof(FontWeight), typeof(LabeledValue), new PropertyMetadata(FontWeights.Normal));

    public LabeledValue()
    {
        InitializeComponent();
    }

    public string Label
    {
        get => (string)GetValue(LabelProperty);
        set => SetValue(LabelProperty, value);
    }

    public string Value
    {
        get => (string)GetValue(ValueProperty);
        set => SetValue(ValueProperty, value);
    }

    public FontWeight ValueWeight
    {
        get => (FontWeight)GetValue(ValueWeightProperty);
        set => SetValue(ValueWeightProperty, value);
    }
}
