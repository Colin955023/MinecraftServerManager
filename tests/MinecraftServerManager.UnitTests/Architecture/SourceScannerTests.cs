using Xunit;

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
}
