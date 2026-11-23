using MinecraftServerManager.App.Services;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerStartPreflightTests : IAsyncDisposable
{
    private readonly TempDirectory _rootTemp = new("msm-preflight-");
    private readonly TempDirectory _backupTemp = new("msm-preflight-bak-");
    private readonly FakeServerRuntimeHost _host = new();
    private readonly ManualUiService _ui = new();
    private readonly SettingsManager _settings;
    private readonly ServerStartPreflight _preflight;

    public ServerStartPreflightTests()
    {
        _settings = new SettingsManager(_rootTemp.FullName);
        _preflight = new ServerStartPreflight(
            _ui,
            _settings,
            new ServerBackupService(_rootTemp.FullName, static () => 10, TimeProvider.System),
            new ServerPropertiesStore(_rootTemp.FullName),
            _host);
    }

    public async ValueTask DisposeAsync()
    {
        await _host.DisposeAsync();
        _rootTemp.Dispose();
        _backupTemp.Dispose();
    }

    private ServerConfig CreateServer(string name, string? port = null, string backupPath = "")
    {
        string dir = Path.Combine(_rootTemp.FullName, name);
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "world.txt"), "data");
        if (port is not null)
        {
            File.WriteAllText(Path.Combine(dir, "server.properties"), $"server-port={port}\n");
        }

        return TestServerConfigs.Create(name, memoryMaxMb: 1024, path: dir, backupPath: backupPath);
    }

    [Fact]
    public async Task CheckAsync_SamePortAsRunningServer_Blocks()
    {
        CreateServer("A", "25570");
        _host.GetFake("A").IsRunning = true;

        bool ok = await _preflight.RunAsync(CreateServer("B", "25570"), TestContext.Current.CancellationToken);

        Assert.False(ok);
        Assert.Contains(_ui.Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("25570", StringComparison.Ordinal));
    }

    [Fact]
    public async Task CheckAsync_DifferentPort_Passes()
    {
        CreateServer("A", "25570");
        _host.GetFake("A").IsRunning = true;

        Assert.True(await _preflight.RunAsync(CreateServer("B", "25571"), TestContext.Current.CancellationToken));
        Assert.Empty(_ui.Notifications);
    }

    [Fact]
    public async Task CheckAsync_UnsetPorts_ConflictAsDefault()
    {
        CreateServer("A");
        _host.GetFake("A").IsRunning = true;

        bool ok = await _preflight.RunAsync(CreateServer("B"), TestContext.Current.CancellationToken);

        Assert.False(ok);
        Assert.Contains(_ui.Notifications, static n => n.Message.Contains("25565", StringComparison.Ordinal));
    }

    [Fact]
    public async Task CheckAsync_AutoBackupDisabled_DoesNotBackup()
    {
        var server = CreateServer("A", backupPath: _backupTemp.FullName);

        Assert.True(await _preflight.RunAsync(server, TestContext.Current.CancellationToken));
        Assert.Empty(Directory.EnumerateFiles(_backupTemp.FullName));
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task CheckAsync_AutoBackupWithoutFolder_ReturnsUserDecision(bool continueStart)
    {
        _settings.UpdatePreferences(p => p with { AutoBackupBeforeStart = true });
        _ui.ConfirmResult = continueStart;

        bool ok = await _preflight.RunAsync(CreateServer("A"), TestContext.Current.CancellationToken);

        Assert.Equal(continueStart, ok);
        Assert.Single(_ui.ConfirmMessages);
    }

    [Fact]
    public async Task CheckAsync_AutoBackupEnabled_CreatesZipAndAllowsStart()
    {
        _settings.UpdatePreferences(p => p with { AutoBackupBeforeStart = true });

        bool ok = await _preflight.RunAsync(CreateServer("A", backupPath: _backupTemp.FullName), TestContext.Current.CancellationToken);

        Assert.True(ok);
        Assert.Single(Directory.EnumerateFiles(_backupTemp.FullName, "backup-A-*.zip"));
        Assert.Contains(_ui.Notifications, static n => n.Type == NotificationType.Success);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task CheckAsync_AutoBackupFails_ReturnsUserDecision(bool continueStart)
    {
        _settings.UpdatePreferences(p => p with { AutoBackupBeforeStart = true });
        _ui.ConfirmResult = continueStart;
        var server = CreateServer("A", backupPath: _backupTemp.FullName);
        Directory.Delete(server.Path, recursive: true);

        bool ok = await _preflight.RunAsync(server, TestContext.Current.CancellationToken);

        Assert.Equal(continueStart, ok);
        Assert.Single(_ui.ConfirmMessages);
        Assert.Contains("失敗", _ui.ConfirmMessages[0], StringComparison.Ordinal);
    }
}
