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

    [GeneratedRegex(@"""(Icon[A-Z]\w*)""")]
    private static partial Regex CodeIconKeyRegex();

    private static Dictionary<string, string> LoadGlyphs() =>
        XDocument.Load(Path.Combine(AppDir, "Resources", "Glyphs.xaml"))
            .Descendants(XamlNs + "String")
            .ToDictionary(static e => (string)e.Attribute(XamlNs + "Key")!, static e => e.Value, StringComparer.Ordinal);

    [Fact]
    public void Glyphs_EachEntry_IsSinglePrivateUseCharacter()
    {
        Dictionary<string, string> glyphs = LoadGlyphs();
        Assert.NotEmpty(glyphs);
        foreach ((string key, string glyph) in glyphs)
        {
            Assert.True(glyph.Length == 1 && glyph[0] is >= '\uE000' and <= '\uF8FF', $"{key} 必須為單一 Segoe Fluent Icons 字碼");
        }
    }

    [Fact]
    public void IconReferences_AllSources_AreDefinedInGlyphs()
    {
        Dictionary<string, string> glyphs = LoadGlyphs();
        var xamlFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.App", "*.xaml")
            .Where(static f => !f.RelativePath.EndsWith("Glyphs.xaml", StringComparison.OrdinalIgnoreCase));
        var xamlKeys = xamlFiles
            .SelectMany(static f => IconReferenceRegex().Matches(SourceScanner.Clean(f.FullPath, File.ReadAllText(f.FullPath), preserveStrings: false)).Select(m => (f.RelativePath, Key: m.Groups[1].Value)));
        var codeKeys = SourceScanner.GetSourceFiles("src/MinecraftServerManager.App")
            .SelectMany(static f => CodeIconKeyRegex().Matches(SourceScanner.Clean(f.FullPath, File.ReadAllText(f.FullPath), preserveStrings: true)).Select(m => (f.RelativePath, Key: m.Groups[1].Value)));
        var references = xamlKeys.Concat(codeKeys).ToList();
        var missing = references.Where(r => !glyphs.ContainsKey(r.Key)).Select(static r => $"{r.RelativePath}:{r.Key}").ToList();

        Assert.Contains(references, static r => r.RelativePath.EndsWith(".cs", StringComparison.Ordinal));
        Assert.True(missing.Count == 0, "Glyphs.xaml 缺少圖示鍵：" + string.Join(", ", missing));

        var referencedKeys = references.Select(static r => r.Key).ToHashSet(StringComparer.Ordinal);
        var orphans = glyphs.Keys.Where(k => !referencedKeys.Contains(k)).ToList();
        Assert.True(orphans.Count == 0, "Glyphs.xaml 存在未使用的孤兒圖示鍵：" + string.Join(", ", orphans));
    }

    [Fact]
    public void FontIcon_AllXamlElements_SpecifySymbolThemeFontFamily()
    {
        var missing = new List<string>();
        foreach ((string relativePath, string fullPath) in SourceScanner.GetSourceFiles("src/MinecraftServerManager.App", "*.xaml"))
        {
            var doc = XDocument.Load(fullPath, LoadOptions.SetLineInfo);
            foreach (XElement element in doc.Descendants().Where(static e => e.Name.LocalName == "FontIcon"))
            {
                string? fontFamily = (string?)element.Attribute("FontFamily");
                if (!string.Equals(fontFamily, "{StaticResource SymbolThemeFontFamily}", StringComparison.Ordinal))
                {
                    int line = element is System.Xml.IXmlLineInfo info && info.HasLineInfo() ? info.LineNumber : 0;
                    missing.Add($"{relativePath}:{line}");
                }
            }
        }

        Assert.True(missing.Count == 0, "以下 <FontIcon> 未顯式指定 FontFamily=\"{StaticResource SymbolThemeFontFamily}\"：" + string.Join(", ", missing));
    }
}
