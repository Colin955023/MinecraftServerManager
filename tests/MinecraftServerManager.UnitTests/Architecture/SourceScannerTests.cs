
namespace MinecraftServerManager.UnitTests.Architecture;

public sealed class SourceScannerTests
{
    [Fact]
    public void StripCommentsOnly_KeepsStringsAndLineLayout()
    {
        const string source = "string a = \"keep.tmp\"; // drop.tmp\r\n/* \"gone\" */ string b = \"// not comment\";";

        string commentsOnly = SourceScanner.StripCommentsOnly(source);
        string both = SourceScanner.StripCommentsAndStrings(source);

        Assert.Equal(source.Length, commentsOnly.Length);
        Assert.Contains("\"keep.tmp\"", commentsOnly, StringComparison.Ordinal);
        Assert.Contains("\"// not comment\"", commentsOnly, StringComparison.Ordinal);
        Assert.DoesNotContain("drop.tmp", commentsOnly, StringComparison.Ordinal);
        Assert.DoesNotContain("gone", commentsOnly, StringComparison.Ordinal);
        Assert.DoesNotContain("keep.tmp", both, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("var a = \"SECRET\"; Keep();")]
    [InlineData("var a = @\"SEC\"\"RET SECRET\"; Keep();")]
    [InlineData("var a = $\"SECRET {b}\"; Keep();")]
    [InlineData("var a = \"\\\"SECRET\\\\\"; Keep();")]
    [InlineData("var a = \"\"\"\nSECRET \"quoted\"\n\"\"\"; Keep();")]
    [InlineData("var c = '\\''; var a = \"SECRET\"; Keep();")]
    [InlineData("/* SECRET\nSECRET */ var a = 1; Keep();")]
    [InlineData("var a = \"// SECRET\"; Keep();")]
    [InlineData("var a = $\"SECRET {new { X = 1 }.X} SECRET\"; Keep();")]
    [InlineData("var c = '\"'; var d = '{'; var a = \"SECRET\"; Keep();")]
    [InlineData("var e = $\"\"; var a = \"SECRET\"; Keep();")]
    [InlineData("var a = $@\"SECRET {{ SECRET }}\"; Keep();")]
    [InlineData("var a = $\"\"\"\nSECRET {b}\n\"\"\"; Keep();")]
    public void StripCommentsAndStrings_RemovesStringContentAndKeepsCode(string source)
    {
        string stripped = SourceScanner.StripCommentsAndStrings(source);

        Assert.DoesNotContain("SECRET", stripped, StringComparison.Ordinal);
        Assert.Contains("Keep();", stripped, StringComparison.Ordinal);
        Assert.Equal(source.Count(static c => c == '\n'), stripped.Count(static c => c == '\n'));
    }
}
