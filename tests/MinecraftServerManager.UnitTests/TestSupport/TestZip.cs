using System.IO.Compression;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用 ZIP 建立工具：以 UTF-8（無 BOM）寫入文字項目，允許重複或穿越路徑等惡意名稱</summary>
internal static class TestZip
{
    /// <summary>於 <paramref name="path"/> 建立含指定文字項目的 ZIP</summary>
    public static void Create(string path, params ReadOnlySpan<(string Name, string Content)> entries)
    {
        using var archive = ZipFile.Open(path, ZipArchiveMode.Create);
        foreach (var (name, content) in entries)
        {
            using var writer = new StreamWriter(archive.CreateEntry(name).Open());
            writer.Write(content);
        }
    }
}
