using System.Xml.Linq;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ColorIconsResourceTests
{
    private static readonly XNamespace XamlNs = "http://schemas.microsoft.com/winfx/2006/xaml";

    [Theory]
    [InlineData("IconCreateServer")]
    [InlineData("IconManageServer")]
    [InlineData("IconMods")]
    [InlineData("IconImport")]
    [InlineData("IconFolder")]
    [InlineData("IconAbout")]
    [InlineData("IconStart")]
    [InlineData("IconConsole")]
    [InlineData("IconServerSettings")]
    [InlineData("IconBackup")]
    [InlineData("IconRestore")]
    [InlineData("IconDelete")]
    [InlineData("IconSearch")]
    [InlineData("IconRefresh")]
    [InlineData("IconWarning")]
    [InlineData("IconCheck")]
    [InlineData("IconUserGroup")]
    public void ColorIconsShouldContainAllRequiredKeys(string resourceKey)
    {
        // 尋找 ColorIcons.xaml 相對路徑
        string basePath = AppContext.BaseDirectory;
        string? candidate = null;
        var dir = new DirectoryInfo(basePath);
        while (dir is not null)
        {
            string path = Path.Combine(dir.FullName, "src", "MinecraftServerManager.App", "Resources", "ColorIcons.xaml");
            if (File.Exists(path))
            {
                candidate = path;
                break;
            }
            dir = dir.Parent;
        }

        Assert.True(candidate is not null && File.Exists(candidate), "找不到 ColorIcons.xaml");

        var doc = XDocument.Load(candidate);
        var keys = doc.Descendants()
            .Select(e => (string?)e.Attribute(XamlNs + "Key"))
            .Where(k => !string.IsNullOrEmpty(k))
            .ToHashSet();

        Assert.Contains(resourceKey, keys);
    }
}
