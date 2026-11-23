using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Utilities;

[Collection("EnvironmentVariableCollection")]
public sealed class RuntimePathsTests
{
    private const string UserDataVariable = "MSM_USER_DATA_DIR";

    [Fact]
    public void CleanupStaleExtractDirectories_StaleSiblings_RemovesOnlyOtherDirectories()
    {
        using var temp = new TempDirectory("msm-unittest-extract-");
        string current = Directory.CreateDirectory(temp.Combine("current")).FullName;
        string stale = Directory.CreateDirectory(temp.Combine("stale")).FullName;
        File.WriteAllText(Path.Combine(stale, "app.dll"), "x");
        string looseFile = temp.Combine("keep.txt");
        File.WriteAllText(looseFile, "x");

        int removed = RuntimePaths.CleanupStaleExtractDirectories(temp, current, DateTime.UtcNow.AddMinutes(1));

        Assert.Equal(1, removed);
        Assert.False(Directory.Exists(stale));
        Assert.True(Directory.Exists(current));
        Assert.True(File.Exists(looseFile));
    }

    [Fact]
    public void CleanupStaleExtractDirectories_DirectoryNewerThanCutoff_KeepsIt()
    {
        using var temp = new TempDirectory("msm-unittest-extract-");
        string current = Directory.CreateDirectory(temp.Combine("current")).FullName;
        string recent = Directory.CreateDirectory(temp.Combine("recent")).FullName;

        int removed = RuntimePaths.CleanupStaleExtractDirectories(temp, current, DateTime.UtcNow.AddMinutes(-1));

        Assert.Equal(0, removed);
        Assert.True(Directory.Exists(recent));
    }

    [Fact]
    public void CleanupStaleExtractDirectories_CurrentOutsideExtractRoot_DeletesNothing()
    {
        using var temp = new TempDirectory("msm-unittest-extract-");
        string root = Directory.CreateDirectory(temp.Combine("root")).FullName;
        string other = Directory.CreateDirectory(temp.Combine("root", "other")).FullName;
        string current = Directory.CreateDirectory(temp.Combine("elsewhere", "current")).FullName;

        int removed = RuntimePaths.CleanupStaleExtractDirectories(root, current, DateTime.UtcNow.AddMinutes(1));

        Assert.Equal(0, removed);
        Assert.True(Directory.Exists(other));
    }

    [Fact]
    public void CleanupStaleExtractDirectories_MissingExtractRoot_ReturnsZero()
    {
        using var temp = new TempDirectory("msm-unittest-extract-");
        string missingRoot = temp.Combine("missing");

        Assert.Equal(0, RuntimePaths.CleanupStaleExtractDirectories(missingRoot, Path.Combine(missingRoot, "current"), DateTime.UtcNow.AddMinutes(1)));
    }

    [Fact]
    public void GetUserDataDir_AbsoluteOverride_ReturnsNormalizedPathAndDerivedDirectories()
    {
        using var temp = new TempDirectory("msm-unittest-data-");
        using var scoped = new ScopedEnvironmentVariable(UserDataVariable, "  " + temp.Combine("sub", "..", "data") + "  ");
        string expected = temp.Combine("data");

        Assert.Equal(expected, RuntimePaths.GetUserDataDir());
        Assert.Equal(Path.Combine(expected, "Logs"), RuntimePaths.GetLogDir());
        Assert.Equal(Path.Combine(expected, "Cache"), RuntimePaths.GetCacheDir());
    }

    [Theory]
    [InlineData("relative\\data")]
    [InlineData("\\rooted-without-drive")]
    [InlineData("C:relative")]
    public void GetUserDataDir_NonFullyQualifiedOverride_Throws(string value)
    {
        using var scoped = new ScopedEnvironmentVariable(UserDataVariable, value);
        Assert.Throws<InvalidOperationException>(RuntimePaths.GetUserDataDir);
    }
}
