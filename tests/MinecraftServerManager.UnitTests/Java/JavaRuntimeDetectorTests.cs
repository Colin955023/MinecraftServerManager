using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Java;

namespace MinecraftServerManager.UnitTests.Java;

/// <summary>Java 執行環境偵測快取、Shim 過濾與版本挑選單元測試</summary>
public sealed class JavaRuntimeDetectorTests
{
    [Fact]
    public async Task DetectAsync_UnchangedFile_UsesCache()
    {
        using var tempDir = new TempDirectory("msm-java-detector-");
        string javaBinDir = Path.Combine(tempDir.FullName, "jdk-21", "bin");
        Directory.CreateDirectory(javaBinDir);
        string javaExe = Path.Combine(javaBinDir, "java.exe");
        File.WriteAllText(javaExe, "fake java binary");

        string cacheDir = tempDir.CreateSubdirectory("cache");
        var environment = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["JAVA_HOME"] = Path.Combine(tempDir.FullName, "jdk-21"),
            ["PATH"] = javaBinDir
        };
        var sources = new JavaSearchSources(
            name => environment.GetValueOrDefault(name),
            InstallRoots: [],
            UserProfileDirectory: null,
            CacheDirectory: cacheDir);

        int processStartCount = 0;
        var runner = new StubProcessRunner(_ =>
        {
            Interlocked.Increment(ref processStartCount);
            return new StubManagedProcess(
                exitCode: 0,
                interactive: false,
                initialOutputs:
                [
                    new ProcessOutput(ProcessOutputKind.StandardError, "openjdk version \"21.0.4\" 2024-07-16 LTS"),
                    new ProcessOutput(ProcessOutputKind.StandardError, "OpenJDK Runtime Environment Temurin-21.0.4+7 (build 21.0.4+7-LTS)"),
                    new ProcessOutput(ProcessOutputKind.StandardError, "OpenJDK 64-Bit Server VM Temurin-21.0.4+7 (build 21.0.4+7-LTS, mixed mode, sharing)")
                ]);
        });

        var detector = new JavaRuntimeDetector(runner, sources);

        // 第一次強制偵測應呼叫外部行程並寫入快取
        var first = await detector.DetectAsync(forceRefresh: true, cancellationToken: TestContext.Current.CancellationToken);
        Assert.Contains(first, j => string.Equals(j.ExecutablePath, javaExe, StringComparison.OrdinalIgnoreCase) && j.MajorVersion == 21);
        Assert.True(processStartCount >= 1);
        Assert.True(File.Exists(Path.Combine(cacheDir, "java_candidates_cache.json")));

        // 新執行個體讀取磁碟快取：若該 java.exe 時間戳記與檔案大小未變，不應對此 javaExe 重新啟動行程
        int targetExeCalls = 0;
        var secondRunner = new StubProcessRunner(spec =>
        {
            if (string.Equals(spec.FileName, javaExe, StringComparison.OrdinalIgnoreCase))
            {
                Interlocked.Increment(ref targetExeCalls);
            }

            return new StubManagedProcess(1);
        });
        var cachedDetector = new JavaRuntimeDetector(secondRunner, sources);
        var second = await cachedDetector.DetectAsync(forceRefresh: false, cancellationToken: TestContext.Current.CancellationToken);

        Assert.Contains(second, j => string.Equals(j.ExecutablePath, javaExe, StringComparison.OrdinalIgnoreCase) && j.MajorVersion == 21);
        Assert.Equal(0, targetExeCalls);
    }

    [Fact]
    public async Task DetectAsync_OracleJavapathShim_FiltersOut()
    {
        using var tempDir = new TempDirectory("msm-java-shim-");
        string shimDir = Path.Combine(tempDir.FullName, "Oracle", "Java", "javapath");
        string realDir = Path.Combine(tempDir.FullName, "jdk-21", "bin");
        Directory.CreateDirectory(shimDir);
        Directory.CreateDirectory(realDir);
        string shimExe = Path.Combine(shimDir, "java.exe");
        string realExe = Path.Combine(realDir, "java.exe");
        File.WriteAllText(shimExe, "shim");
        File.WriteAllText(realExe, "real");

        var env = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["PATH"] = $"{shimDir}{Path.PathSeparator}{realDir}",
        };
        var sources = new JavaSearchSources(
            name => env.GetValueOrDefault(name),
            InstallRoots: [],
            UserProfileDirectory: null,
            CacheDirectory: Path.Combine(tempDir.FullName, "cache"));

        var probedPaths = new List<string>();
        var runner = new StubProcessRunner(spec =>
        {
            lock (probedPaths)
            {
                probedPaths.Add(spec.FileName);
            }

            return CreateJavaVersionProcess(21, is64Bit: true);
        });

        var detector = new JavaRuntimeDetector(runner, sources);
        var runtimes = await detector.DetectAsync(forceRefresh: true, cancellationToken: TestContext.Current.CancellationToken);

        Assert.Single(runtimes);
        Assert.Equal(realExe, runtimes[0].ExecutablePath, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain(probedPaths, p => p.Equals(shimExe, StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task FindBestMatchAsync_MultipleVersionsAndBitness_PrefersExact64Bit()
    {
        using var tempDir = new TempDirectory("msm-java-match-");
        string jdk17Dir = Path.Combine(tempDir.FullName, "jdk-17", "bin");
        string jdk21x86Dir = Path.Combine(tempDir.FullName, "jdk-21-x86", "bin");
        string jdk21x64Dir = Path.Combine(tempDir.FullName, "jdk-21-x64", "bin");
        Directory.CreateDirectory(jdk17Dir);
        Directory.CreateDirectory(jdk21x86Dir);
        Directory.CreateDirectory(jdk21x64Dir);

        string exe17 = Path.Combine(jdk17Dir, "java.exe");
        string exe21x86 = Path.Combine(jdk21x86Dir, "java.exe");
        string exe21x64 = Path.Combine(jdk21x64Dir, "java.exe");
        File.WriteAllText(exe17, "17");
        File.WriteAllText(exe21x86, "21-32");
        File.WriteAllText(exe21x64, "21-64");

        var env = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["PATH"] = string.Join(Path.PathSeparator, jdk17Dir, jdk21x86Dir, jdk21x64Dir),
        };
        var sources = new JavaSearchSources(
            name => env.GetValueOrDefault(name),
            InstallRoots: [],
            UserProfileDirectory: null,
            CacheDirectory: Path.Combine(tempDir.FullName, "cache"));

        var runner = new StubProcessRunner(spec =>
        {
            if (spec.FileName.Equals(exe17, StringComparison.OrdinalIgnoreCase))
            {
                return CreateJavaVersionProcess(17, is64Bit: true);
            }

            if (spec.FileName.Equals(exe21x86, StringComparison.OrdinalIgnoreCase))
            {
                return CreateJavaVersionProcess(21, is64Bit: false);
            }

            return CreateJavaVersionProcess(21, is64Bit: true);
        });

        var detector = new JavaRuntimeDetector(runner, sources);

        var match21 = await detector.FindBestMatchAsync(21, TestContext.Current.CancellationToken);
        var match25 = await detector.FindBestMatchAsync(25, TestContext.Current.CancellationToken);

        Assert.NotNull(match21);
        Assert.Equal(exe21x64, match21.ExecutablePath, StringComparer.OrdinalIgnoreCase);
        Assert.True(match21.Is64Bit);
        Assert.Null(match25);
    }

    [Fact]
    public async Task DetectAsync_ModifiedCachedExecutable_ReprobesAndWritesUpdatedCache()
    {
        using var tempDir = new TempDirectory("msm-java-cache-update-");
        string javaBinDir = Path.Combine(tempDir.FullName, "jdk", "bin");
        Directory.CreateDirectory(javaBinDir);
        string javaExe = Path.Combine(javaBinDir, "java.exe");
        File.WriteAllText(javaExe, "java-v21");
        File.SetLastWriteTimeUtc(javaExe, new DateTime(2025, 1, 1, 0, 0, 0, DateTimeKind.Utc));

        string cacheDir = Path.Combine(tempDir.FullName, "cache");
        var env = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["JAVA_HOME"] = Path.Combine(tempDir.FullName, "jdk"),
        };
        var sources = new JavaSearchSources(
            name => env.GetValueOrDefault(name),
            InstallRoots: [],
            UserProfileDirectory: null,
            CacheDirectory: cacheDir);

        var initialDetector = new JavaRuntimeDetector(new StubProcessRunner(_ => CreateJavaVersionProcess(21, is64Bit: true)), sources);
        var initial = await initialDetector.DetectAsync(forceRefresh: true, cancellationToken: TestContext.Current.CancellationToken);
        Assert.Contains(initial, j => j.MajorVersion == 21);

        // 變更檔案大小與修改時間以使快取失效
        File.WriteAllText(javaExe, "java-v22-updated-binary");
        File.SetLastWriteTimeUtc(javaExe, new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc));

        int reprobeCount = 0;
        var updatedDetector = new JavaRuntimeDetector(
            new StubProcessRunner(_ =>
            {
                Interlocked.Increment(ref reprobeCount);
                return CreateJavaVersionProcess(22, is64Bit: true);
            }),
            sources);
        var updated = await updatedDetector.DetectAsync(forceRefresh: false, cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal(1, reprobeCount);
        Assert.Contains(updated, j => j.ExecutablePath.Equals(javaExe, StringComparison.OrdinalIgnoreCase) && j.MajorVersion == 22);

        // 確認已回寫快取：再次建立偵測器不應重啟行程
        int thirdProbeCount = 0;
        var thirdDetector = new JavaRuntimeDetector(
            new StubProcessRunner(_ =>
            {
                Interlocked.Increment(ref thirdProbeCount);
                return new StubManagedProcess(1);
            }),
            sources);
        var cachedAgain = await thirdDetector.DetectAsync(forceRefresh: false, cancellationToken: TestContext.Current.CancellationToken);

        Assert.Equal(0, thirdProbeCount);
        Assert.Contains(cachedAgain, j => j.ExecutablePath.Equals(javaExe, StringComparison.OrdinalIgnoreCase) && j.MajorVersion == 22);
    }

    private static StubManagedProcess CreateJavaVersionProcess(int major, bool is64Bit) =>
        new(
            exitCode: 0,
            interactive: false,
            initialOutputs:
            [
                new ProcessOutput(ProcessOutputKind.StandardError, $"openjdk version \"{major}.0.1\" 2024-10-15"),
                new ProcessOutput(ProcessOutputKind.StandardError, $"OpenJDK Runtime Environment (build {major}.0.1+1)"),
                new ProcessOutput(ProcessOutputKind.StandardError, is64Bit
                    ? $"OpenJDK 64-Bit Server VM (build {major}.0.1+1, mixed mode)"
                    : $"OpenJDK Client VM (build {major}.0.1+1, mixed mode)")
            ]);
}
