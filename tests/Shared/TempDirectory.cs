namespace MinecraftServerManager.TestSupport;

/// <summary>測試專用暫存目錄：建立唯一目錄，Dispose 時清除唯讀屬性並重試刪除（防毒或索引服務可能短暫佔用），清理失敗不影響測試結果</summary>
internal sealed class TempDirectory : IDisposable
{
    private const int DeleteAttempts = 3;

    public TempDirectory(string prefix = "msm-test-") =>
        FullName = Directory.CreateTempSubdirectory(prefix).FullName;

    /// <summary>暫存目錄完整路徑</summary>
    public string FullName { get; }

    /// <summary>組合暫存目錄下的子路徑</summary>
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
