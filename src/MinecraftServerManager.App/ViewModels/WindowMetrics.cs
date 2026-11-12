namespace MinecraftServerManager.App.ViewModels;

/// <summary>主視窗與所在螢幕的即時尺寸：視窗為邏輯像素（與儲存設定、預設大小一致），螢幕為實體像素</summary>
public readonly record struct WindowMetrics(int WindowWidth, int WindowHeight, int ScreenWidth, int ScreenHeight, double Scale);
