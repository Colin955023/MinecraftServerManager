namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用暫存目錄，Dispose 時刪除</summary>
internal sealed class TempDirectory : IDisposable
{
    private const int DeleteAttempts = 3;

    /// <summary>不穿透 reparse point，避免殘留 Junction 導致修改外部檔案屬性</summary>
    private static readonly EnumerationOptions CleanupEnumeration = new()
    {
        RecurseSubdirectories = true,
        AttributesToSkip = FileAttributes.ReparsePoint
    };

    public TempDirectory(string prefix = "msm-test-") =>
        FullName = Directory.CreateTempSubdirectory(prefix).FullName;

    public string FullName { get; }

    public string Combine(params ReadOnlySpan<string> parts) =>
        Path.Combine(FullName, Path.Combine(parts));

    /// <summary>於此目錄下建立子目錄並回傳完整路徑</summary>
    public string CreateSubdirectory(string name) =>
        Directory.CreateDirectory(Path.Combine(FullName, name)).FullName;

    public static implicit operator string(TempDirectory directory) => directory.FullName;

    public override string ToString() => FullName;

    public void Dispose()
    {
        for (int attempt = 1; Directory.Exists(FullName); attempt++)
        {
            try
            {
                foreach (string entry in Directory.EnumerateFileSystemEntries(FullName, "*", CleanupEnumeration))
                {
                    File.SetAttributes(entry, FileAttributes.Normal);
                }

                Directory.Delete(FullName, recursive: true);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                if (attempt >= DeleteAttempts)
                {
                    ReportLeftover($"暫存目錄清理失敗，已殘留：{FullName}（{ex.GetType().Name}: {ex.Message}）");
                    return;
                }

                Thread.Sleep(50);
            }
        }
    }

    /// <summary>測試脈絡內寫入測試警告；於 ProcessExit 等非測試脈絡（<see cref="TestContext.Current"/> 為 null）改寫到 stderr</summary>
    private static void ReportLeftover(string message)
    {
        var context = TestContext.Current;
        if (context is null)
        {
            Console.Error.WriteLine(message);
            return;
        }

        context.AddWarning(message);
    }
}
