using System.Diagnostics;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用 NTFS junction；Dispose 只移除連結本身，不動目標內容</summary>
internal sealed class TestJunction : IDisposable
{
    private readonly string _link;

    public TestJunction(string link, string target)
    {
        _link = link;
        var startInfo = new ProcessStartInfo("cmd.exe")
        {
            CreateNoWindow = true,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        startInfo.ArgumentList.Add("/c");
        startInfo.ArgumentList.Add("mklink");
        startInfo.ArgumentList.Add("/J");
        startInfo.ArgumentList.Add(link);
        startInfo.ArgumentList.Add(target);
        using var process = System.Diagnostics.Process.Start(startInfo) ?? throw new InvalidOperationException("無法啟動 cmd.exe");
        process.StandardOutput.ReadToEnd();
        process.StandardError.ReadToEnd();
        process.WaitForExit();
        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException($"建立 junction 失敗：{link}");
        }
    }

    public void Dispose()
    {
        if (Directory.Exists(_link))
        {
            Directory.Delete(_link, recursive: false);
        }
    }
}
