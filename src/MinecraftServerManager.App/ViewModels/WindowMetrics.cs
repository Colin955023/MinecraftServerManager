namespace MinecraftServerManager.App.ViewModels;

/// <summary>主視窗（邏輯像素）與所在螢幕（實體像素）的尺寸</summary>
public readonly record struct WindowMetrics(int WindowWidth, int WindowHeight, int ScreenWidth, int ScreenHeight, double Scale);
