namespace MinecraftServerManager.App.Services;

/// <summary>
/// UI 執行緒計時器控制點（與 UI 框架原生型別解耦）
/// </summary>
public interface IUiTimer
{
    public void StartTimer();

    public void StopTimer();
}
