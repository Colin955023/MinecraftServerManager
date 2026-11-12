using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>會修改行程層級環境變數（如 MSM_USER_DATA_DIR）的測試集合，停用平行化以免影響其他測試類別</summary>
[CollectionDefinition("EnvironmentVariableCollection", DisableParallelization = true)]
public sealed class EnvironmentVariableCollectionDefinition;
