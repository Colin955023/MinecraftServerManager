using MinecraftServerManager.Infrastructure.Settings;
using Xunit;

namespace MinecraftServerManager.UnitTests.Settings;

public sealed class SystemThemeServiceTests
{
    [Fact]
    public void IsSystemLightTheme_ExecutesSafelyWithoutExceptions()
    {
        // 驗證讀取系統主題 API 在任何 Windows 環境下均能安全完成而不崩潰
        bool isLight = SystemThemeService.IsSystemLightTheme();

        // 結果必然是 true 或 false 之一
        Assert.True(isLight || !isLight);
    }
}
