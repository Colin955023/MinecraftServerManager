using Windows.UI;

namespace MinecraftServerManager.App.Services;

/// <summary>強調色彩服務抽象：套用自訂或系統強調色並通知變更</summary>
public interface IAccentColorService
{
    /// <summary>強調色彩變更（含跟隨系統時的系統強調色變更）後觸發</summary>
    public event Action? AccentColorChanged;

    /// <summary>取得目前 Windows 系統的強調色彩</summary>
    public Color GetSystemAccentColor();

    /// <summary>套用強調色彩；<paramref name="customHex"/> 為空時使用系統色彩與系統原生色階</summary>
    public void ApplyAccentColor(string? customHex);
}
