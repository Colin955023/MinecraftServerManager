using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class LaunchArgumentListTests
{
    [Fact]
    public void BuildJvmAndTargetArgs_JarTarget_AddsMemoryEncodingGcAndNoGui()
    {
        var args = ServerLaunchPlanner.BuildJvmAndTargetArgs(LoaderKind.Vanilla, "server.jar", 1024, 2048, [], javaMajor: 21);

        Assert.Equal("-Xms1024M", args[0]);
        Assert.Equal("-Xmx2048M", args[1]);
        Assert.Contains("-Dstdout.encoding=UTF-8", args);
        Assert.Contains("-Dstderr.encoding=UTF-8", args);
        Assert.True(JvmOptionPolicy.HasGcOption(args));
        string[] expectedTail = ["-jar", "server.jar", "nogui"];
        Assert.Equal(expectedTail, args.TakeLast(3));
    }

    [Fact]
    public void BuildJvmAndTargetArgs_CustomEncodingProvided_DoesNotAddDefaultEncoding()
    {
        var args = ServerLaunchPlanner.BuildJvmAndTargetArgs(LoaderKind.Vanilla, "server.jar", 1024, 2048, ["-Dstdout.encoding=GBK"], javaMajor: null);

        Assert.Contains("-Dstdout.encoding=GBK", args);
        Assert.DoesNotContain("-Dstdout.encoding=UTF-8", args);
        Assert.Contains("-Dstderr.encoding=UTF-8", args);
    }

    [Fact]
    public void BuildJvmAndTargetArgs_ArgumentFileTarget_UsesArgfileWithoutJarFlag()
    {
        const string target = "@libraries/net/minecraftforge/forge/1.20.1-47.2.0/win_args.txt";

        var args = ServerLaunchPlanner.BuildJvmAndTargetArgs(LoaderKind.Forge, target, 1024, 2048, [], javaMajor: null);

        Assert.DoesNotContain("-jar", args);
        Assert.Equal(target, args[^2]);
        Assert.Equal("nogui", args[^1]);
    }

    [Fact]
    public void BuildJvmAndTargetArgs_PaperLoader_UsesDoubleDashNoGui()
    {
        var args = ServerLaunchPlanner.BuildJvmAndTargetArgs(LoaderKind.Paper, "paper-1.21.4-164.jar", 1024, 2048, [], javaMajor: null);

        Assert.Equal("--nogui", args[^1]);
    }

    [Fact]
    public void StartScriptWriter_Write_ProducesSameArgumentListInStartScript()
    {
        using var dir = new TempDirectory();

        StartScriptWriter.Write(dir.FullName, "server.jar", 2048, 1024, @"C:\Java\bin\java.exe", ["-Dcustom=1"], LoaderKind.Vanilla);

        string script = File.ReadAllText(Path.Combine(dir.FullName, "start_server.bat"));
        Assert.Contains("-Xms1024M -Xmx2048M", script);
        Assert.Contains("-Dstdout.encoding=UTF-8", script);
        Assert.Contains("-Dstderr.encoding=UTF-8", script);
        Assert.Contains("-Dcustom=1 -jar \"server.jar\" nogui %*", script);
    }

    [Fact]
    public void StartScriptWriter_Write_JarTarget_QuotesJarNameAndPassesSafeScriptValidator()
    {
        using var dir = new TempDirectory("msm-script-jar-");
        File.WriteAllText(Path.Combine(dir.FullName, "server.jar"), "jar");

        StartScriptWriter.Write(dir.FullName, "server.jar", 2048, 1024, @"C:\Java\bin\java.exe", null, LoaderKind.Vanilla, javaMajor: 21);

        string scriptPath = Path.Combine(dir.FullName, "start_server.bat");
        Assert.Contains("-jar \"server.jar\" nogui %*", File.ReadAllText(scriptPath));
        Assert.True(SafeScriptValidator.ValidateScriptContent(scriptPath, dir.FullName));
    }

    [Fact]
    public void StartScriptWriter_Write_ArgumentFileTarget_UsesQuotedAtPathAndPassesSafeScriptValidator()
    {
        using var dir = new TempDirectory("msm-script-argfile-");

        StartScriptWriter.Write(dir.FullName, "@libraries/net/minecraftforge/forge/win_args.txt", 2048, 1024, @"C:\Java\bin\java.exe", null, LoaderKind.Forge, javaMajor: 21);

        string scriptPath = Path.Combine(dir.FullName, "start_server.bat");
        string script = File.ReadAllText(scriptPath);
        Assert.Contains("@\"libraries/net/minecraftforge/forge/win_args.txt\" nogui %*", script);
        Assert.DoesNotContain("-jar", script);
        Assert.True(SafeScriptValidator.ValidateScriptContent(scriptPath, dir.FullName));
    }

    [Fact]
    public void StartScriptWriter_Write_JavaTwentyOne_UsesZgcInsteadOfG1()
    {
        using var dir = new TempDirectory("msm-script-zgc-");

        StartScriptWriter.Write(dir.FullName, "server.jar", 2048, 1024, @"C:\Java\bin\java.exe", null, LoaderKind.Vanilla, javaMajor: 21);

        string script = File.ReadAllText(Path.Combine(dir.FullName, "start_server.bat"));
        Assert.Contains("-XX:+UseZGC", script);
        Assert.DoesNotContain("-XX:+UseG1GC", script);
    }

    [Fact]
    public void CreatePlan_DirectLaunchWithJavaMajor_RefreshesManagedScriptWithSameArguments()
    {
        using var dir = new TempDirectory("msm-script-refresh-");
        string javaExe = Path.Combine(dir.FullName, "java.exe");
        File.WriteAllText(javaExe, string.Empty);
        File.WriteAllText(Path.Combine(dir.FullName, "server.jar"), "jar");
        string scriptPath = Path.Combine(dir.FullName, "start_server.bat");
        StartScriptWriter.Write(dir.FullName, "server.jar", 2048, 1024, javaExe, null, LoaderKind.Vanilla, javaMajor: 17);
        Assert.Contains("-XX:+UseG1GC", File.ReadAllText(scriptPath));

        var config = TestServerConfigs.Create(path: dir.FullName, memoryMaxMb: 2048, memoryMinMb: 1024);
        new ServerLaunchPlanner().CreatePlan(config, "server.jar", javaExe, javaMajor: 21);

        string script = File.ReadAllText(scriptPath);
        Assert.Contains("-XX:+UseZGC", script);
        Assert.DoesNotContain("-XX:+UseG1GC", script);
        Assert.Contains($"\"{javaExe}\" -Xms1024M -Xmx2048M", script);
        Assert.Contains("-jar \"server.jar\" nogui %*", script);
    }

    [Fact]
    public void CreatePlan_ScriptLaunch_DoesNotRewriteStartScript()
    {
        using var dir = new TempDirectory("msm-script-selfwrite-");
        string javaExe = Path.Combine(dir.FullName, "java.exe");
        File.WriteAllText(javaExe, string.Empty);
        File.WriteAllText(Path.Combine(dir.FullName, "server.jar"), "jar");
        string scriptPath = Path.Combine(dir.FullName, "start_server.bat");
        StartScriptWriter.Write(dir.FullName, "server.jar", 2048, 1024, javaExe, null, LoaderKind.Vanilla, javaMajor: 17);
        string before = File.ReadAllText(scriptPath);

        var config = TestServerConfigs.Create(path: dir.FullName, memoryMaxMb: 2048, memoryMinMb: 1024);
        var plan = new ServerLaunchPlanner().CreatePlan(config, "start_server.bat", javaExe, javaMajor: 21);

        Assert.True(plan.IsScript);
        Assert.Equal(before, File.ReadAllText(scriptPath));
    }

    [Fact]
    public void CreatePlan_DirectLaunchWithUnmanagedStartScript_DoesNotOverwrite()
    {
        using var dir = new TempDirectory("msm-script-unmanaged-");
        string javaExe = Path.Combine(dir.FullName, "java.exe");
        File.WriteAllText(javaExe, string.Empty);
        File.WriteAllText(Path.Combine(dir.FullName, "server.jar"), "jar");
        string scriptPath = Path.Combine(dir.FullName, "start_server.bat");
        const string custom = "@echo off\r\necho custom\r\n";
        File.WriteAllText(scriptPath, custom);

        var config = TestServerConfigs.Create(path: dir.FullName, memoryMaxMb: 2048, memoryMinMb: 1024);
        new ServerLaunchPlanner().CreatePlan(config, "server.jar", javaExe, javaMajor: 21);

        Assert.Equal(custom, File.ReadAllText(scriptPath));
    }

    [Fact]
    public void ValidateJavaPath_BareNonJavaName_Throws() => Assert.Throws<InvalidOperationException>(() => SafeScriptValidator.ValidateJavaPath("python"));

    [Fact]
    public void ValidateJavaPath_BareJavaName_DoesNotThrow() => SafeScriptValidator.ValidateJavaPath("java");
}
