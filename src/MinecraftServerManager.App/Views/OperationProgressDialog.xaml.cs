using System.ComponentModel;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 通用作業進度視窗（具備 Shimmer 動態流光光效與平滑數值推進動畫）
/// </summary>
public partial class OperationProgressDialog : Window
{
    private static readonly QuadraticEase ProgressEase = new() { EasingMode = EasingMode.EaseOut };
    private readonly Storyboard _shimmerStoryboard = new();
    private bool _completed;
    private double _currentPercent;

    public OperationProgressDialog(string windowTitle, string heading, string initialMessage)
    {
        InitializeComponent();
        Title = windowTitle;
        TitleText.Text = heading;
        PhaseText.Text = initialMessage;

        Loaded += OnDialogLoaded;
        Closing += OnDialogClosing;
        Closed += OnDialogClosed;
        SizeChanged += OnDialogSizeChanged;
    }

    private void OnDialogLoaded(object sender, RoutedEventArgs e)
    {
        SetupShimmerAnimation();
        UpdateFillWidthAnimated(_currentPercent, animate: false);
    }

    private void SetupShimmerAnimation()
    {
        double trackWidth = ProgressTrackContainer.ActualWidth > 0 ? ProgressTrackContainer.ActualWidth : 472;
        var anim = new DoubleAnimation
        {
            From = -160,
            To = trackWidth + 160,
            Duration = TimeSpan.FromSeconds(1.8),
            RepeatBehavior = RepeatBehavior.Forever,
        };

        Storyboard.SetTarget(anim, ShimmerTransform);
        Storyboard.SetTargetProperty(anim, new PropertyPath(TranslateTransform.XProperty));

        _shimmerStoryboard.Children.Clear();
        _shimmerStoryboard.Children.Add(anim);
        _shimmerStoryboard.Begin();
    }

    private void OnDialogSizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (IsLoaded)
        {
            SetupShimmerAnimation();
            UpdateFillWidthAnimated(_currentPercent, animate: false);
        }
    }

    /// <summary>
    /// 標記流程結束，解除防誤關閉鎖定
    /// </summary>
    public void MarkCompleted() => _completed = true;

    /// <summary>
    /// 更新百分比與階段訊息（具備 250ms 平滑過渡插值動畫）
    /// </summary>
    public void UpdateProgress(int percent, string message)
    {
        int pct = Math.Clamp(percent, 0, 100);
        RunOnUi(() =>
        {
            _currentPercent = pct;
            PercentText.Text = $"{pct}%";
            if (!string.IsNullOrWhiteSpace(message))
            {
                PhaseText.Text = message;
            }

            UpdateFillWidthAnimated(pct, animate: true);
        });
    }

    /// <summary>
    /// 更新進度數量與階段訊息
    /// </summary>
    public void UpdateProgress(int current, int total, string message)
    {
        int pct = total > 0 ? (int)Math.Clamp(current * 100.0 / total, 0, 100) : 0;
        RunOnUi(() =>
        {
            _currentPercent = pct;
            PercentText.Text = $"{pct}% ({current}/{total})";
            if (!string.IsNullOrWhiteSpace(message))
            {
                PhaseText.Text = message;
            }

            UpdateFillWidthAnimated(pct, animate: true);
        });
    }

    private void UpdateFillWidthAnimated(double percent, bool animate)
    {
        double trackWidth = ProgressTrackContainer.ActualWidth > 0 ? ProgressTrackContainer.ActualWidth : 472;
        double targetWidth = Math.Clamp(percent / 100.0 * trackWidth, 0, trackWidth);

        if (!animate || !IsLoaded)
        {
            ProgressFill.BeginAnimation(WidthProperty, null);
            ProgressFill.Width = targetWidth;
            return;
        }

        var widthAnimation = new DoubleAnimation
        {
            To = targetWidth,
            Duration = TimeSpan.FromMilliseconds(250),
            EasingFunction = ProgressEase,
        };

        ProgressFill.BeginAnimation(WidthProperty, widthAnimation, HandoffBehavior.SnapshotAndReplace);
    }

    private void RunOnUi(Action action)
    {
        if (Dispatcher.CheckAccess())
        {
            action();
        }
        else
        {
            _ = Dispatcher.BeginInvoke(action);
        }
    }

    private void OnDialogClosing(object? sender, CancelEventArgs e) =>
        e.Cancel = !_completed;

    private void OnDialogClosed(object? sender, EventArgs e)
    {
        try
        {
            _shimmerStoryboard.Stop();
            _shimmerStoryboard.Children.Clear();
        }
        catch
        {
        }
    }
}
