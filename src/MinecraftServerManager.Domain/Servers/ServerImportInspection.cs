using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器匯入候選檢查快照（不會修改來源）
/// </summary>
public sealed record ServerImportInspection
{
    public string TransactionId { get; }
    public ImportMode Mode { get; }
    public ImportSourceKind SourceKind { get; }
    public string SourcePath { get; }
    public ServerName Name { get; }
    public string FinalPath { get; }
    public ServerInspection Server { get; }
    public IReadOnlyList<string> Warnings { get; }
    public bool Committable { get; }
    public ConflictType ConflictType { get; }
    public ImportManifest? Manifest { get; }

    public ServerImportInspection(
        string transactionId,
        ImportMode mode,
        ImportSourceKind sourceKind,
        string sourcePath,
        ServerName name,
        string finalPath,
        ServerInspection server,
        IEnumerable<string>? warnings = null,
        bool committable = false,
        ConflictType conflictType = ConflictType.None,
        ImportManifest? manifest = null)
    {
        TransactionId = transactionId ?? string.Empty;
        Mode = mode;
        SourceKind = sourceKind;
        SourcePath = sourcePath ?? string.Empty;
        Name = name;
        FinalPath = finalPath ?? string.Empty;
        Server = server;
        Warnings = (warnings ?? []).ToArray();
        Committable = committable;
        ConflictType = conflictType;
        Manifest = manifest;
    }

    /// <summary>
    /// 建立提交時使用的伺服器持久化設定模型
    /// </summary>
    public ServerConfig BuildConfig(string path, ServerConfig? previous = null)
    {
        var mcVersion = MinecraftVersion.TryParse(Server.MinecraftVersion, out var parsedMc)
            ? parsedMc
            : (previous?.MinecraftVersion ?? MinecraftVersion.Parse("1.20.1"));

        var loaderKind = Enum.TryParse<LoaderKind>(Server.LoaderType, true, out var parsedLoader)
            ? parsedLoader
            : (previous?.LoaderType ?? LoaderKind.Vanilla);

        return new ServerConfig(
            Name,
            mcVersion,
            loaderKind,
            Server.LoaderVersion,
            Server.MemoryMaxMb,
            Server.MemoryMinMb,
            path: path,
            jvmArgs: previous?.JvmArgs ?? [],
            backupPath: previous?.BackupPath ?? string.Empty
        );
    }
}
