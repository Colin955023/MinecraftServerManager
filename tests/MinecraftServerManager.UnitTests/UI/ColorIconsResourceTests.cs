using System.Collections.Frozen;
using System.Xml.Linq;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ColorIconsResourceTests
{
    private static readonly XNamespace XamlNs = "http://schemas.microsoft.com/winfx/2006/xaml";
    private static readonly FrozenSet<string> DefinedResourceKeys = LoadResourceKeys();

    private static FrozenSet<string> LoadResourceKeys()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            string path = Path.Combine(dir.FullName, "src", "MinecraftServerManager.App", "Resources", "ColorIcons.xaml");
            if (File.Exists(path))
            {
                var doc = XDocument.Load(path);
                return doc.Descendants()
                    .Select(e => (string?)e.Attribute(XamlNs + "Key"))
                    .Where(static k => !string.IsNullOrEmpty(k))
                    .Select(static k => k!)
                    .ToFrozenSet(StringComparer.Ordinal);
            }

            dir = dir.Parent;
        }

        throw new FileNotFoundException("找不到 ColorIcons.xaml");
    }

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
    public void ColorIconsShouldContainAllRequiredKeys(string resourceKey) =>
        Assert.Contains(resourceKey, (IReadOnlySet<string>)DefinedResourceKeys);
}
