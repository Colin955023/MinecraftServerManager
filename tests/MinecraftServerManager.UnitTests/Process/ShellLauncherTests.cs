using System.ComponentModel;
using System.Diagnostics;
using MinecraftServerManager.Infrastructure.Process;

namespace MinecraftServerManager.UnitTests.Process;

public sealed class ShellLauncherTests
{
    private static (ShellLauncher Launcher, List<ProcessStartInfo> Started) CreateRecordingLauncher()
    {
        var started = new List<ProcessStartInfo>();
        return (new ShellLauncher(started.Add), started);
    }

    [Fact]
    public void OpenFile_DangerousExtension_RejectsWithoutShellExecution()
    {
        using var temp = new TempDirectory("msm-reject-");
        string tempFile = temp.Combine("reject.exe");
        File.WriteAllText(tempFile, "dummy");
        var (launcher, started) = CreateRecordingLauncher();

        Assert.False(launcher.OpenFile(tempFile));
        Assert.Empty(started);
    }

    [Fact]
    public void OpenFile_Trusted_SkipsExtensionRejectionAndStartsShellWithFullPath()
    {
        using var temp = new TempDirectory("msm-trusted-");
        string tempFile = temp.Combine("tool.exe");
        File.WriteAllText(tempFile, "dummy");
        var (launcher, started) = CreateRecordingLauncher();

        Assert.True(launcher.OpenFile(tempFile, isTrusted: true));
        var info = Assert.Single(started);
        Assert.True(info.UseShellExecute);
        Assert.Equal(Path.GetFullPath(tempFile), info.FileName);
    }

    [Fact]
    public void OpenFile_TrustedButMissingOrEmpty_ReturnsFalseWithoutShellExecution()
    {
        using var temp = new TempDirectory("msm-shell-missing-");
        var (launcher, started) = CreateRecordingLauncher();

        Assert.False(launcher.OpenFile(string.Empty, isTrusted: true));
        Assert.False(launcher.OpenFile(temp.Combine("missing.html"), isTrusted: true));
        Assert.Empty(started);
    }

    [Fact]
    public void OpenFile_ShellStartThrows_ReturnsFalse()
    {
        using var temp = new TempDirectory("msm-shellfail-");
        string tempFile = temp.Combine("notes.txt");
        File.WriteAllText(tempFile, "dummy");
        var launcher = new ShellLauncher(static _ => throw new Win32Exception(2));

        Assert.False(launcher.OpenFile(tempFile));
    }

    [Theory]
    [InlineData("https://modrinth.com/mod/x", true)]
    [InlineData("http://example.com/", true)]
    [InlineData("file:///C:/Windows/System32/cmd.exe", false)]
    [InlineData("ms-settings:privacy", false)]
    [InlineData("not a url", false)]
    public void OpenUrl_Scheme_OnlyHttpAndHttpsReachShell(string url, bool expected)
    {
        var (launcher, started) = CreateRecordingLauncher();

        Assert.Equal(expected, launcher.OpenUrl(url));
        Assert.Equal(expected ? 1 : 0, started.Count);
    }

    [Fact]
    public void ShowInFolder_ExistingFile_StartsExplorerWithEscapedSelectArguments()
    {
        using var temp = new TempDirectory("msm-select-");
        string tempFile = temp.Combine("a b&c.txt");
        File.WriteAllText(tempFile, "dummy");
        var (launcher, started) = CreateRecordingLauncher();

        Assert.True(launcher.ShowInFolder(tempFile));
        var info = Assert.Single(started);
        Assert.False(info.UseShellExecute);
        Assert.Equal("explorer.exe", Path.GetFileName(info.FileName), ignoreCase: true);
        Assert.Equal(["/select,", Path.GetFullPath(tempFile)], info.ArgumentList);
    }

    [Fact]
    public void OpenFolder_MissingDirectory_ReturnsFalseWithoutShellExecution()
    {
        using var temp = new TempDirectory("msm-shell-missing-");
        var (launcher, started) = CreateRecordingLauncher();

        Assert.False(launcher.OpenFolder(temp.Combine("missing")));
        Assert.Empty(started);
    }

    [Fact]
    public void OpenFolder_ExistingDirectory_StartsShellWithFullPath()
    {
        using var temp = new TempDirectory("msm-openfolder-");
        var (launcher, started) = CreateRecordingLauncher();

        Assert.True(launcher.OpenFolder(temp.FullName));
        var info = Assert.Single(started);
        Assert.True(info.UseShellExecute);
        Assert.Equal(Path.GetFullPath(temp.FullName), info.FileName);
    }

    [Fact]
    public void OpenTargets_ShellStartThrows_ReturnFalse()
    {
        using var temp = new TempDirectory("msm-shellthrow-");
        string tempFile = temp.Combine("notes.txt");
        File.WriteAllText(tempFile, "dummy");
        var launcher = new ShellLauncher(static _ => throw new Win32Exception(2));

        Assert.False(launcher.OpenFolder(temp.FullName));
        Assert.False(launcher.ShowInFolder(tempFile));
        Assert.False(launcher.OpenUrl("https://example.com/"));
    }

    [Fact]
    public void ShowInFolder_MissingFile_ReturnsFalseWithoutShellExecution()
    {
        using var temp = new TempDirectory("msm-shell-missing-");
        var (launcher, started) = CreateRecordingLauncher();

        Assert.False(launcher.ShowInFolder(temp.Combine("missing.txt")));
        Assert.Empty(started);
    }
}
