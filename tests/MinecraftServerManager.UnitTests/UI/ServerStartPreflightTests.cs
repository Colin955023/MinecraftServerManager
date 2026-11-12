using MinecraftServerManager.App.Services;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;
using Xunit;

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
            new ServerBackupService(_rootTemp.FullName, static () => 10),
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

        return new ServerConfig(ServerName.Parse(name), MinecraftVersion.Parse("1.21.4"), LoaderKind.Vanilla, string.Empty, 1024, null, path: dir, backupPath: backupPath);
    }

    [Fact]
    public async Task SamePortAsRunningServer_IsBlocked()
    {
        CreateServer("A", "25570");
        _host.GetFake("A").IsRunning = true;

        bool ok = await _preflight.RunAsync(CreateServer("B", "25570"));

        Assert.False(ok);
        Assert.Contains(_ui.Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("25570", StringComparison.Ordinal));
    }

    [Fact]
    public async Task DifferentPort_Passes()
    {
        CreateServer("A", "25570");
        _host.GetFake("A").IsRunning = true;

        Assert.True(await _preflight.RunAsync(CreateServer("B", "25571")));
        Assert.Empty(_ui.Notifications);
    }

    [Fact]
    public async Task UnsetPorts_AreTreatedAsDefaultAndConflict()
    {
        CreateServer("A");
        _host.GetFake("A").IsRunning = true;

        bool ok = await _preflight.RunAsync(CreateServer("B"));

        Assert.False(ok);
        Assert.Contains(_ui.Notifications, static n => n.Message.Contains("25565", StringComparison.Ordinal));
    }

    [Fact]
    public async Task AutoBackupDisabled_DoesNotBackup()
    {
        var server = CreateServer("A", backupPath: _backupTemp.FullName);

        Assert.True(await _preflight.RunAsync(server));
        Assert.Empty(Directory.EnumerateFiles(_backupTemp.FullName));
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task AutoBackupWithoutBackupFolder_ReturnsUserDecision(bool continueStart)
    {
        _settings.SetAutoBackupBeforeStartEnabled(true);
        _ui.ConfirmResult = continueStart;

        bool ok = await _preflight.RunAsync(CreateServer("A"));

        Assert.Equal(continueStart, ok);
        Assert.Single(_ui.ConfirmMessages);
    }

    [Fact]
    public async Task AutoBackupEnabled_CreatesZipAndAllowsStart()
    {
        _settings.SetAutoBackupBeforeStartEnabled(true);

        bool ok = await _preflight.RunAsync(CreateServer("A", backupPath: _backupTemp.FullName));

        Assert.True(ok);
        Assert.Single(Directory.EnumerateFiles(_backupTemp.FullName, "backup-A-*.zip"));
        Assert.Contains(_ui.Notifications, static n => n.Type == NotificationType.Success);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task AutoBackupFailure_ReturnsUserDecision(bool continueStart)
    {
        _settings.SetAutoBackupBeforeStartEnabled(true);
        _ui.ConfirmResult = continueStart;
        var server = CreateServer("A", backupPath: _backupTemp.FullName);
        Directory.Delete(server.Path, recursive: true);

        bool ok = await _preflight.RunAsync(server);

        Assert.Equal(continueStart, ok);
        Assert.Single(_ui.ConfirmMessages);
        Assert.Contains("失敗", _ui.ConfirmMessages[0], StringComparison.Ordinal);
    }
}
