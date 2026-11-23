using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MinecraftServerManager.App.Controls;

/// <summary>忙碌進度條與狀態說明組合控制項</summary>
public sealed partial class BusyStatusIndicator : UserControl
{
    public static readonly DependencyProperty IsBusyProperty =
        DependencyProperty.Register(nameof(IsBusy), typeof(bool), typeof(BusyStatusIndicator), new PropertyMetadata(false, OnVisualStatePropertyChanged));

    public static readonly DependencyProperty MessageProperty =
        DependencyProperty.Register(nameof(Message), typeof(string), typeof(BusyStatusIndicator), new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty BusyNameProperty =
        DependencyProperty.Register(nameof(BusyName), typeof(string), typeof(BusyStatusIndicator), new PropertyMetadata("處理中"));

    public static readonly DependencyProperty UseAccentForegroundProperty =
        DependencyProperty.Register(nameof(UseAccentForeground), typeof(bool), typeof(BusyStatusIndicator), new PropertyMetadata(false, OnVisualStatePropertyChanged));

    public static readonly DependencyProperty HideMessageWhenIdleProperty =
        DependencyProperty.Register(nameof(HideMessageWhenIdle), typeof(bool), typeof(BusyStatusIndicator), new PropertyMetadata(false, OnVisualStatePropertyChanged));

    public BusyStatusIndicator()
    {
        InitializeComponent();
        UpdateMessageAppearance();
    }

    public bool IsBusy
    {
        get => (bool)GetValue(IsBusyProperty);
        set => SetValue(IsBusyProperty, value);
    }

    public string Message
    {
        get => (string)GetValue(MessageProperty);
        set => SetValue(MessageProperty, value);
    }

    public string BusyName
    {
        get => (string)GetValue(BusyNameProperty);
        set => SetValue(BusyNameProperty, value);
    }

    public bool UseAccentForeground
    {
        get => (bool)GetValue(UseAccentForegroundProperty);
        set => SetValue(UseAccentForegroundProperty, value);
    }

    public bool HideMessageWhenIdle
    {
        get => (bool)GetValue(HideMessageWhenIdleProperty);
        set => SetValue(HideMessageWhenIdleProperty, value);
    }

    private static void OnVisualStatePropertyChanged(DependencyObject d, DependencyPropertyChangedEventArgs e) =>
        ((BusyStatusIndicator)d).UpdateMessageAppearance();

    private void UpdateMessageAppearance()
    {
        MessageTextBlock.Visibility = HideMessageWhenIdle && !IsBusy ? Visibility.Collapsed : Visibility.Visible;
        if (UseAccentForeground)
        {
            ThemeBrush.SetForegroundKey(MessageTextBlock, UiBindHelpers.AccentTextBrushKey);
        }
        else
        {
            MessageTextBlock.ClearValue(ThemeBrush.ForegroundKeyProperty);
            MessageTextBlock.ClearValue(TextBlock.ForegroundProperty);
        }
    }
}
