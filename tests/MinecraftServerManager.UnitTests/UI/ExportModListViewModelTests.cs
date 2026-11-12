using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ExportModListViewModelTests
{
    [Fact]
    public async Task ExportAsync_WhenUserCancelsFilePicker_ReturnsFalse()
    {
        var fakeUi = new ManualUiService { SaveFileResult = null };
        var fakeExporter = new FakeExporter();
        var vm = new ExportModListViewModel("TestServer", [], fakeExporter, NoOp.Create<IExternalLauncher>(), fakeUi);

        bool result = await vm.ExportAsync(ModListExportFormat.Json);

        Assert.False(result);
        Assert.False(fakeExporter.ExportCalled);
    }

    [Fact]
    public async Task ExportAsync_WhenSuccessAndUserConfirms_OpensFileAndReturnsTrue()
    {
        var fakeUi = new ManualUiService
        {
            SaveFileResult = @"C:\Exports\mods.json",
            ConfirmResult = true
        };
        var fakeExporter = new FakeExporter();
        var fakeLauncher = new RecordingLauncher();
        var vm = new ExportModListViewModel("TestServer", [], fakeExporter, fakeLauncher, fakeUi);

        bool result = await vm.ExportAsync(ModListExportFormat.Json);

        Assert.True(result);
        Assert.True(fakeExporter.ExportCalled);
        Assert.Equal(@"C:\Exports\mods.json", fakeExporter.SavedPath);
        Assert.Contains(@"C:\Exports\mods.json", fakeLauncher.OpenedFiles);
    }

    [Fact]
    public async Task ExportAsync_WhenExporterThrows_ShowsErrorAndReturnsFalse()
    {
        var fakeUi = new ManualUiService
        {
            SaveFileResult = @"C:\Exports\mods.json"
        };
        var fakeExporter = new FakeExporter { ShouldThrow = true };
        var vm = new ExportModListViewModel("TestServer", [], fakeExporter, NoOp.Create<IExternalLauncher>(), fakeUi);

        bool result = await vm.ExportAsync(ModListExportFormat.Json);

        Assert.False(result);
        Assert.NotEmpty(fakeUi.ErrorMessages);
    }

    [Fact]
    public async Task ExportAsync_WhenOpenConfirmationFails_StillReturnsTrueWithoutError()
    {
        var fakeUi = new ManualUiService
        {
            SaveFileResult = @"C:\Exports\mods.html",
            ConfirmThrows = true
        };
        var fakeExporter = new FakeExporter();
        var vm = new ExportModListViewModel("TestServer", [], fakeExporter, new RecordingLauncher(), fakeUi);

        bool result = await vm.ExportAsync(ModListExportFormat.Html);

        Assert.True(result);
        Assert.True(fakeExporter.ExportCalled);
        Assert.Empty(fakeUi.ErrorMessages);
        Assert.NotEmpty(fakeUi.Notifications);
    }

    private sealed class FakeExporter : IModListExporter
    {
        public bool ExportCalled { get; private set; }
        public string? SavedPath { get; private set; }
        public bool ShouldThrow { get; init; }

        public Task ExportAsync(IReadOnlyList<ModListExportRow> rows, ModListExportFormat format, string filePath, CancellationToken cancellationToken = default)
        {
            if (ShouldThrow)
            {
                throw new InvalidOperationException("磁碟已滿");
            }

            ExportCalled = true;
            SavedPath = filePath;
            return Task.CompletedTask;
        }
    }
}
