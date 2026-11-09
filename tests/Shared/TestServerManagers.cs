using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.TestSupport;

/// <summary>
/// 建立不連網、不安裝載入器的測試用 ServerManager（載入器安裝改由 <see cref="StubLoaderInstaller"/> 代勞）
/// </summary>
internal static class TestServerManagers
{
    public static ServerManager Create(string serversRoot, IServerInspector? inspector = null) =>
        new(
            serversRoot,
            inspector ?? new ServerInspector(),
            new StubLoaderInstaller(),
            NoOp.Create<IJavaRuntimeDetector>(),
            NoOp.Create<IMinecraftJavaRequirementService>());
}
