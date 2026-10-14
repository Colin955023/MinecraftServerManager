namespace MinecraftServerManager.App.Services;

/// <summary>
/// UI 執行緒計時器控制點（與 WPF 型別解耦）
/// </summary>
public interface IUiTimer
{
    public void StartTimer();

    public void StopTimer();
}
