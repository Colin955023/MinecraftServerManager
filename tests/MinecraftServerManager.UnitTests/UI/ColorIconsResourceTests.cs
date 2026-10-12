using System.Windows;
using System.Windows.Markup;
using System.Xml;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ColorIconsResourceTests
{
    [Theory]
    [InlineData("IconCreateServer")]
    [InlineData("IconManageServer")]
    [InlineData("IconMods")]
    [InlineData("IconImport")]
    [InlineData("IconFolder")]
    [InlineData("IconAbout")]
    [InlineData("IconStart")]
    [InlineData("IconStop")]
    [InlineData("IconConsole")]
    [InlineData("IconServerSettings")]
    [InlineData("IconBackup")]
    [InlineData("IconRestore")]
    [InlineData("IconDelete")]
    [InlineData("IconSearch")]
    [InlineData("IconRefresh")]
    [InlineData("IconWarning")]
    [InlineData("IconGlobe")]
    [InlineData("IconCheck")]
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

        using var fileStream = File.OpenRead(candidate);
        using var xmlReader = XmlReader.Create(fileStream);
        var resourceDictionary = (ResourceDictionary)XamlReader.Load(xmlReader);

        Assert.True(resourceDictionary.Contains(resourceKey), $"ColorIcons.xaml 遺漏圖示資源: {resourceKey}");
    }
}
