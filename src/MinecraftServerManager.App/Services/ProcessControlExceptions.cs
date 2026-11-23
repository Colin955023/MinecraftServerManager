using System.ComponentModel;

namespace MinecraftServerManager.App.Services;

/// <summary>程序控制（停止、傳送指令）之可預期失敗例外判定；命中時僅記錄警告，不中斷流程</summary>
public static class ProcessControlExceptions
{
    /// <summary>判斷是否為可預期的程序控制失敗（I/O、已釋放、狀態不符或 Win32 錯誤）</summary>
    public static bool IsExpected(Exception exception) =>
        exception is IOException or InvalidOperationException or ObjectDisposedException or Win32Exception;
}
