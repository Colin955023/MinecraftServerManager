using System.Text.RegularExpressions;

namespace MinecraftServerManager.UnitTests.Architecture;

public sealed class SourceScannerTests
{
    [Fact]
    public void StripCommentsOnly_CodeWithStrings_KeepsStringsAndLineLayout()
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
    [InlineData("var a = $\"SECRET {F(\"SECRET\")} SECRET\"; Keep();")]
    [InlineData("var a = $\"SECRET {b /* SECRET */}\"; Keep();")]
    [InlineData("var a = $$\"\"\"\n{SECRET} {{b}} SECRET\n\"\"\"; Keep();")]
    [InlineData("var a = $$\"\"\"\n{{F(\"SECRET\")}}\n\"\"\"; Keep();")]
    public void StripCommentsAndStrings_CodeWithStrings_RemovesStringContent(string source)
    {
        string stripped = SourceScanner.StripCommentsAndStrings(source);

        Assert.DoesNotContain("SECRET", stripped, StringComparison.Ordinal);
        Assert.Contains("Keep();", stripped, StringComparison.Ordinal);
        Assert.Equal(source.Count(static c => c == '\n'), stripped.Count(static c => c == '\n'));
    }

    [Theory]
    [InlineData("var a = $\"x {Keep()} y\";")]
    [InlineData("var a = $\"\"\"\nx {Keep()} y\n\"\"\";")]
    [InlineData("var a = $$\"\"\"\n{x} {{Keep()}} y\n\"\"\";")]
    public void StripCommentsAndStrings_InterpolatedString_KeepsHoleCode(string source) =>
        Assert.Contains("Keep()", SourceScanner.StripCommentsAndStrings(source), StringComparison.Ordinal);

    [Fact]
    public void StripXamlComments_XamlWithComments_RemovesOnlyComments()
    {
        const string xaml = "<Grid Tag=\"http://x/'a'\" />\n<!-- <Button Click=\"Gone\" />\nGone -->\n<TextBlock Text=\"Keep\" />";

        string stripped = SourceScanner.StripXamlComments(xaml);

        Assert.Contains("http://x/'a'", stripped, StringComparison.Ordinal);
        Assert.Contains("Text=\"Keep\"", stripped, StringComparison.Ordinal);
        Assert.DoesNotContain("Gone", stripped, StringComparison.Ordinal);
        Assert.Equal(xaml.Count(static c => c == '\n'), stripped.Count(static c => c == '\n'));
    }

    [Fact]
    public void ScanViolations_Multiline_ReportsStartLineOfCrossLineMatch()
    {
        using var temp = new TempDirectory("msm-unittest-scanner-");
        string file = temp.Combine("Sample.cs");
        File.WriteAllText(file, "class A\n{\n    void M() => Foo(\n        Bar);\n}\n");
        var regex = new Regex(@"Foo\(\s*Bar\)");

        var single = SourceScanner.ScanViolations([("Sample.cs", file)], regex, "T", "t", static _ => false);
        var multi = SourceScanner.ScanViolations([("Sample.cs", file)], regex, "T", "t", static _ => false, multiline: true);

        Assert.Empty(single);
        Assert.Equal(3, Assert.Single(multi).LineNumber);
    }
}
