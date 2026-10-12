using MinecraftServerManager.Core.Ports;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class JavaRuntimeDetectorTests
{
    [Fact]
    public async Task FindBestMatchPrefersExact64Bit()
    {
        var testRuntimes = new List<JavaRuntimeInfo>
        {
            new("C:\\Java\\jdk-8\\bin\\java.exe", 8, Is64Bit: true, JavawPath: "C:\\Java\\jdk-8\\bin\\javaw.exe"),
            new("C:\\Java\\jdk-17-x86\\bin\\java.exe", 17, Is64Bit: false, JavawPath: "C:\\Java\\jdk-17-x86\\bin\\javaw.exe"),
            new("C:\\Java\\jdk-17-x64\\bin\\java.exe", 17, Is64Bit: true, JavawPath: "C:\\Java\\jdk-17-x64\\bin\\javaw.exe"),
            new("C:\\Java\\jdk-21\\bin\\java.exe", 21, Is64Bit: true, JavawPath: "C:\\Java\\jdk-21\\bin\\javaw.exe"),
        };

        var detector = new FakeDetector(testRuntimes);
        var match = await detector.FindBestMatchAsync(17);

        Assert.NotNull(match);
        Assert.Equal(17, match.MajorVersion);
        Assert.True(match.Is64Bit);
        Assert.Equal("C:\\Java\\jdk-17-x64\\bin\\java.exe", match.ExecutablePath);
    }

    [Fact]
    public async Task FindBestMatchFallsBackToHigherCompatibleMajor()
    {
        var testRuntimes = new List<JavaRuntimeInfo>
        {
            new("C:\\Java\\jdk-8\\bin\\java.exe", 8, Is64Bit: true),
            new("C:\\Java\\jdk-21\\bin\\java.exe", 21, Is64Bit: true),
        };

        var detector = new FakeDetector(testRuntimes);
        var match = await detector.FindBestMatchAsync(17);

        Assert.NotNull(match);
        Assert.Equal(21, match.MajorVersion);
    }

    [Fact]
    public async Task FindBestMatchReturnsNullWhenNoCompatibleVersion()
    {
        var testRuntimes = new List<JavaRuntimeInfo>
        {
            new("C:\\Java\\jdk-8\\bin\\java.exe", 8, Is64Bit: true),
            new("C:\\Java\\jdk-11\\bin\\java.exe", 11, Is64Bit: true),
        };

        var detector = new FakeDetector(testRuntimes);
        var match = await detector.FindBestMatchAsync(17);

        Assert.Null(match);
    }

    private sealed class FakeDetector(IReadOnlyList<JavaRuntimeInfo> runtimes) : IJavaRuntimeDetector
    {
        public Task<IReadOnlyList<JavaRuntimeInfo>> DetectAsync(bool forceRefresh = false, CancellationToken cancellationToken = default) =>
            Task.FromResult(runtimes);

        public Task<JavaRuntimeInfo?> FindBestMatchAsync(int targetMajor, CancellationToken cancellationToken = default)
        {
            var exact64 = runtimes.FirstOrDefault(r => r.MajorVersion == targetMajor && r.Is64Bit);
            if (exact64 is not null)
            {
                return Task.FromResult<JavaRuntimeInfo?>(exact64);
            }

            var exact = runtimes.FirstOrDefault(r => r.MajorVersion == targetMajor);
            if (exact is not null)
            {
                return Task.FromResult<JavaRuntimeInfo?>(exact);
            }

            return Task.FromResult(runtimes
                .Where(r => r.MajorVersion > targetMajor)
                .OrderBy(r => r.MajorVersion)
                .ThenByDescending(r => r.Is64Bit)
                .FirstOrDefault());
        }
    }
}
