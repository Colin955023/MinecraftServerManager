using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 螢幕右下角非阻塞浮動提示視窗
/// </summary>
public sealed partial class ToastWindow : Window
{
    private static ToastWindow? _instance;
    private static readonly Lock SyncLock = new();

    public static ToastWindow Instance
    {
        get
        {
            if (_instance is null)
            {
                lock (SyncLock)
                {
                    _instance ??= new ToastWindow();
                }
            }
            return _instance;
        }
    }

    public ToastWindow()
    {
        InitializeComponent();
        Loaded += (_, _) => UpdatePosition();
        SizeChanged += (_, _) => UpdatePosition();
    }

    private void UpdatePosition()
    {
        var workArea = SystemParameters.WorkArea;
        Left = workArea.Right - ActualWidth - 12;
        Top = workArea.Bottom - ActualHeight - 12;
    }

    /// <summary>
    /// 顯示一筆 Toast 提示
    /// </summary>
    public void ShowToast(string message, string? title = null, ToastType type = ToastType.Info, int durationSeconds = 3)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.InvokeAsync(() => ShowToast(message, title, type, durationSeconds));
            return;
        }

        switch (type)
        {
            case ToastType.Warning:
                System.Media.SystemSounds.Exclamation.Play();
                break;
            case ToastType.Error:
                System.Media.SystemSounds.Hand.Play();
                break;
            case ToastType.Info:
            case ToastType.Success:
            default:
                System.Media.SystemSounds.Asterisk.Play();
                break;
        }

        // 最多保留 4 個，超過則從頂部移除舊的
        while (ToastContainer.Children.Count >= 4)
        {
            ToastContainer.Children.RemoveAt(0);
        }

        var (icon, accentBrushKey) = type switch
        {
            ToastType.Success => ("✔", "SuccessBrush"),
            ToastType.Warning => ("⚠", "WarningBrush"),
            ToastType.Error => ("✖", "DangerBrush"),
            _ => ("ℹ", "AccentBrush")
        };

        var border = new Border
        {
            Margin = new Thickness(0, 0, 0, 8),
            CornerRadius = new CornerRadius(8),
            MinWidth = 280,
            MaxWidth = 420,
            BorderThickness = new Thickness(1),
            Opacity = 0,
            RenderTransform = new TranslateTransform(40, 0)
        };

        border.SetResourceReference(Border.BackgroundProperty, "CardBrush");
        border.SetResourceReference(Border.BorderBrushProperty, accentBrushKey);

        var grid = new Grid { Margin = new Thickness(14, 10, 12, 10) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        var iconBlock = new TextBlock
        {
            Text = icon,
            FontSize = 16,
            FontWeight = FontWeights.Bold,
            Margin = new Thickness(0, 2, 10, 0),
            VerticalAlignment = VerticalAlignment.Top
        };
        iconBlock.SetResourceReference(TextBlock.ForegroundProperty, accentBrushKey);
        Grid.SetColumn(iconBlock, 0);
        grid.Children.Add(iconBlock);

        var textPanel = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
        if (!string.IsNullOrWhiteSpace(title))
        {
            var titleBlock = new TextBlock
            {
                Text = title,
                FontWeight = FontWeights.SemiBold,
                FontSize = 13,
                Margin = new Thickness(0, 0, 0, 2),
                TextTrimming = TextTrimming.CharacterEllipsis
            };
            titleBlock.SetResourceReference(TextBlock.ForegroundProperty, "TextBrush");
            textPanel.Children.Add(titleBlock);
        }

        var msgBlock = new TextBlock
        {
            Text = message,
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            LineHeight = 18
        };
        msgBlock.SetResourceReference(TextBlock.ForegroundProperty, "TextBrush");
        textPanel.Children.Add(msgBlock);

        Grid.SetColumn(textPanel, 1);
        grid.Children.Add(textPanel);

        var closeButton = new Button
        {
            Content = "✕",
            FontSize = 11,
            Width = 20,
            Height = 20,
            Padding = new Thickness(0),
            Margin = new Thickness(8, 0, 0, 0),
            VerticalAlignment = VerticalAlignment.Top,
            Background = Brushes.Transparent,
            BorderThickness = new Thickness(0),
            Cursor = System.Windows.Input.Cursors.Hand
        };
        closeButton.SetResourceReference(ForegroundProperty, "MutedTextBrush");
        Grid.SetColumn(closeButton, 2);
        grid.Children.Add(closeButton);

        border.Child = grid;

        // 計時器與動畫
        var timer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(Math.Max(1, durationSeconds))
        };

        void Dismiss()
        {
            timer.Stop();
            var fadeOut = new DoubleAnimation(0.0, TimeSpan.FromMilliseconds(200));
            var slideOut = new DoubleAnimation(-15, TimeSpan.FromMilliseconds(200));

            fadeOut.Completed += (_, _) =>
            {
                ToastContainer.Children.Remove(border);
                if (ToastContainer.Children.Count == 0)
                {
                    Hide();
                }
            };

            border.BeginAnimation(OpacityProperty, fadeOut);
            border.RenderTransform.BeginAnimation(TranslateTransform.YProperty, slideOut);
        }

        timer.Tick += (_, _) => Dismiss();
        closeButton.Click += (_, _) => Dismiss();

        border.MouseEnter += (_, _) => timer.Stop();
        border.MouseLeave += (_, _) => timer.Start();

        ToastContainer.Children.Add(border);

        if (!IsVisible)
        {
            Show();
        }

        UpdatePosition();

        // 進入動畫
        var fadeIn = new DoubleAnimation(1.0, TimeSpan.FromMilliseconds(220));
        var slideIn = new DoubleAnimation(0.0, TimeSpan.FromMilliseconds(220))
        {
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
        };

        border.BeginAnimation(OpacityProperty, fadeIn);
        border.RenderTransform.BeginAnimation(TranslateTransform.XProperty, slideIn);

        timer.Start();
    }
}
