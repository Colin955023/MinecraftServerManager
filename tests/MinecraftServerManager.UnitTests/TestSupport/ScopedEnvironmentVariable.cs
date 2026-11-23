namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>設定環境變數並於 Dispose 時還原原值；需搭配 <c>EnvironmentVariableCollection</c> 避免平行測試互相干擾</summary>
internal sealed class ScopedEnvironmentVariable : IDisposable
{
    private readonly string _name;
    private readonly string? _original;

    public ScopedEnvironmentVariable(string name, string? value)
    {
        _name = name;
        _original = Environment.GetEnvironmentVariable(name);
        Environment.SetEnvironmentVariable(name, value);
    }

    public void Dispose() => Environment.SetEnvironmentVariable(_name, _original);
}
