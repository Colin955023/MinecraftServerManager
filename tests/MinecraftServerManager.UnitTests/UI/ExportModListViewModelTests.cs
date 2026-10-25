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
        var fakeUi = new FakeUiService { SaveFileResult = null };
        var fakeExporter = new FakeExporter();
        var vm = new ExportModListViewModel("TestServer", [], fakeExporter, null, fakeUi);

        bool result = await vm.ExportAsync(ModListExportFormat.Json);

        Assert.False(result);
        Assert.False(fakeExporter.ExportCalled);
    }

    [Fact]
    public async Task ExportAsync_WhenSuccessAndUserConfirms_OpensFileAndReturnsTrue()
    {
        var fakeUi = new FakeUiService
        {
            SaveFileResult = @"C:\Exports\mods.json",
            ConfirmResult = true
        };
        var fakeExporter = new FakeExporter();
        var fakeLauncher = new FakeLauncher();
        var vm = new ExportModListViewModel("TestServer", [], fakeExporter, fakeLauncher, fakeUi);

        bool result = await vm.ExportAsync(ModListExportFormat.Json);

        Assert.True(result);
        Assert.True(fakeExporter.ExportCalled);
        Assert.Equal(@"C:\Exports\mods.json", fakeExporter.SavedPath);
        Assert.True(fakeLauncher.OpenFileCalled);
        Assert.Equal(@"C:\Exports\mods.json", fakeLauncher.OpenedPath);
    }

    [Fact]
    public async Task ExportAsync_WhenExporterThrows_ShowsErrorAndReturnsFalse()
    {
        var fakeUi = new FakeUiService
        {
            SaveFileResult = @"C:\Exports\mods.json"
        };
        var fakeExporter = new FakeExporter { ShouldThrow = true };
        var vm = new ExportModListViewModel("TestServer", [], fakeExporter, null, fakeUi);

        bool result = await vm.ExportAsync(ModListExportFormat.Json);

        Assert.False(result);
        Assert.True(fakeUi.ShowErrorCalled);
    }

    private sealed class FakeUiService : NoOpUiService
    {
        public string? SaveFileResult { get; init; }
        public bool ConfirmResult { get; init; }
        public bool ShowErrorCalled { get; private set; }

        public override string? PickSaveFile(string title, string fileName, string filter) => SaveFileResult;

        public override bool Confirm(string message, string title, UiMessageLevel level = UiMessageLevel.Question) => ConfirmResult;

        public override void ShowError(string message, string title) => ShowErrorCalled = true;
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

    private sealed class FakeLauncher : IExternalLauncher
    {
        public bool OpenFileCalled { get; private set; }
        public string? OpenedPath { get; private set; }

        public bool OpenFile(string filePath, bool isTrusted = false)
        {
            OpenFileCalled = true;
            OpenedPath = filePath;
            return true;
        }

        public bool OpenFolder(string folderPath, bool isTrusted = false) => true;
        public bool ShowInFolder(string filePath, bool isTrusted = false) => true;
        public bool OpenUrl(string url, bool isTrusted = false) => true;
    }
}
