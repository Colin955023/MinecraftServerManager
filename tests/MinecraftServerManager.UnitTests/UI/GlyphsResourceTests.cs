using System.Text.RegularExpressions;
using System.Xml.Linq;
using MinecraftServerManager.UnitTests.Architecture;

namespace MinecraftServerManager.UnitTests.UI;

public sealed partial class GlyphsResourceTests
{
    private static readonly XNamespace XamlNs = "http://schemas.microsoft.com/winfx/2006/xaml";
    private static readonly string AppDir = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.App");

    [GeneratedRegex(@"\{StaticResource (Icon\w+)\}")]
    private static partial Regex IconReferenceRegex();

    private static Dictionary<string, string> LoadGlyphs() =>
        XDocument.Load(Path.Combine(AppDir, "Resources", "Glyphs.xaml"))
            .Descendants(XamlNs + "String")
            .ToDictionary(static e => (string)e.Attribute(XamlNs + "Key")!, static e => e.Value, StringComparer.Ordinal);

    [Fact]
    public void Glyphs_ShouldBeSinglePrivateUseCharacter()
    {
        Dictionary<string, string> glyphs = LoadGlyphs();
        Assert.NotEmpty(glyphs);
        foreach ((string key, string glyph) in glyphs)
        {
            Assert.True(glyph.Length == 1 && glyph[0] is >= '\uE000' and <= '\uF8FF', $"{key} 必須為單一 Segoe Fluent Icons 字碼");
        }
    }

    [Fact]
    public void IconReferences_ShouldBeDefinedInGlyphs()
    {
        Dictionary<string, string> glyphs = LoadGlyphs();
        var missing = SourceScanner.GetSourceFiles("src/MinecraftServerManager.App", "*.xaml")
            .SelectMany(static f => IconReferenceRegex().Matches(File.ReadAllText(f.FullPath)).Select(m => $"{f.RelativePath}:{m.Groups[1].Value}"))
            .Where(r => !glyphs.ContainsKey(r[(r.LastIndexOf(':') + 1)..]))
            .ToList();
        Assert.True(missing.Count == 0, "Glyphs.xaml 缺少圖示鍵：" + string.Join(", ", missing));
    }
}
