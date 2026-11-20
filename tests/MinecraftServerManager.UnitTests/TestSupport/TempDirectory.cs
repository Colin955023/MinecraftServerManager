namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用暫存目錄，Dispose 時刪除</summary>
internal sealed class TempDirectory : IDisposable
{
    private const int DeleteAttempts = 3;

    public TempDirectory(string prefix = "msm-test-") =>
        FullName = Directory.CreateTempSubdirectory(prefix).FullName;

    public string FullName { get; }

    public string Combine(params ReadOnlySpan<string> parts) =>
        Path.Combine(FullName, Path.Combine(parts));

    public static implicit operator string(TempDirectory directory) => directory.FullName;

    public override string ToString() => FullName;

    public void Dispose()
    {
        for (int attempt = 1; Directory.Exists(FullName); attempt++)
        {
            try
            {
                foreach (string entry in Directory.EnumerateFileSystemEntries(FullName, "*", SearchOption.AllDirectories))
                {
                    File.SetAttributes(entry, FileAttributes.Normal);
                }

                Directory.Delete(FullName, recursive: true);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                if (attempt >= DeleteAttempts)
                {
                    return;
                }

                Thread.Sleep(50);
            }
        }
    }
}
