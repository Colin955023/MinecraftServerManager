namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器檢查的用途與既有身分期待值
/// </summary>
public sealed record ServerInspectionIntent
{
    public InspectionPurpose Purpose { get; }
    public string ExpectedLoaderType { get; }
    public string ExpectedMinecraftVersion { get; }
    public string ExpectedLoaderVersion { get; }

    public ServerInspectionIntent(
        InspectionPurpose purpose,
        string expectedLoaderType = "",
        string expectedMinecraftVersion = "",
        string expectedLoaderVersion = "")
    {
        Purpose = purpose;
        ExpectedLoaderType = expectedLoaderType ?? string.Empty;
        ExpectedMinecraftVersion = expectedMinecraftVersion ?? string.Empty;
        ExpectedLoaderVersion = expectedLoaderVersion ?? string.Empty;
    }

    public static ServerInspectionIntent ForImport() => new(InspectionPurpose.Import);
    public static ServerInspectionIntent ForRedetect() => new(InspectionPurpose.Redetect);
    public static ServerInspectionIntent ForStatus() => new(InspectionPurpose.Status);
    public static ServerInspectionIntent ForLaunch() => new(InspectionPurpose.Launch);
}
