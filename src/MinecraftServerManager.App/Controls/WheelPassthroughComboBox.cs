using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;

namespace MinecraftServerManager.App.Controls;

/// <summary>收合時滑鼠滾輪不切換選項、交由外層捲動頁面的下拉選單</summary>
public sealed partial class WheelPassthroughComboBox : ComboBox
{
    /// <summary>WinUI 預設於聚焦且收合時以滾輪切換選項；略過基底處理並保留未處理狀態，讓事件冒泡至外層 ScrollViewer</summary>
    protected override void OnPointerWheelChanged(PointerRoutedEventArgs e)
    {
        if (IsDropDownOpen)
        {
            base.OnPointerWheelChanged(e);
        }
    }
}
