
namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>會修改行程環境變數的測試集合，停用平行化</summary>
[CollectionDefinition("EnvironmentVariableCollection", DisableParallelization = true)]
public sealed class EnvironmentVariableCollectionDefinition;
