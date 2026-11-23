using System.Windows.Input;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Windows.System;

namespace MinecraftServerManager.App.Controls;

/// <summary>文字框快速鍵：Ctrl+F 聚焦（僅可見時生效）、Enter 執行 EnterCommand</summary>
public static class TextBoxShortcuts
{
    public static readonly DependencyProperty FocusOnCtrlFProperty =
        DependencyProperty.RegisterAttached(
            "FocusOnCtrlF",
            typeof(bool),
            typeof(TextBoxShortcuts),
            new PropertyMetadata(false, OnFocusOnCtrlFChanged));

    public static readonly DependencyProperty EnterCommandProperty =
        DependencyProperty.RegisterAttached(
            "EnterCommand",
            typeof(ICommand),
            typeof(TextBoxShortcuts),
            new PropertyMetadata(null, OnEnterCommandChanged));

    public static bool GetFocusOnCtrlF(DependencyObject obj) => (bool)obj.GetValue(FocusOnCtrlFProperty);

    public static void SetFocusOnCtrlF(DependencyObject obj, bool value) => obj.SetValue(FocusOnCtrlFProperty, value);

    public static ICommand? GetEnterCommand(DependencyObject obj) => (ICommand?)obj.GetValue(EnterCommandProperty);

    public static void SetEnterCommand(DependencyObject obj, ICommand? value) => obj.SetValue(EnterCommandProperty, value);

    private static readonly DependencyProperty CtrlFAcceleratorProperty =
        DependencyProperty.RegisterAttached(
            "CtrlFAccelerator",
            typeof(KeyboardAccelerator),
            typeof(TextBoxShortcuts),
            new PropertyMetadata(null));

    private static void OnFocusOnCtrlFChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not TextBox textBox)
        {
            return;
        }

        if (textBox.GetValue(CtrlFAcceleratorProperty) is KeyboardAccelerator existing)
        {
            textBox.KeyboardAccelerators.Remove(existing);
            textBox.ClearValue(CtrlFAcceleratorProperty);
        }

        if (e.NewValue is true)
        {
            var accelerator = new KeyboardAccelerator { Modifiers = VirtualKeyModifiers.Control, Key = VirtualKey.F };
            accelerator.Invoked += static (_, args) => args.Handled = args.Element is TextBox tb && tb.Focus(FocusState.Keyboard);
            textBox.KeyboardAccelerators.Add(accelerator);
            textBox.SetValue(CtrlFAcceleratorProperty, accelerator);
        }
    }

    private static void OnEnterCommandChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not TextBox textBox)
        {
            return;
        }

        textBox.KeyDown -= OnKeyDown;
        if (e.NewValue is not null)
        {
            textBox.KeyDown += OnKeyDown;
        }
    }

    private static void OnKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter && GetEnterCommand((TextBox)sender) is { } command && command.TryExecute())
        {
            e.Handled = true;
        }
    }
}
