using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.Infrastructure.Serialization;

/// <summary>
/// 應用程式集中管理的 System.Text.Json 源產生器（Source Generator）內容，
/// 編譯期生成序列化中繼資料以達成零反射、低記憶體與高吞吐 JSON 處理。
/// </summary>
[JsonSourceGenerationOptions(
    PropertyNamingPolicy = JsonKnownNamingPolicy.Unspecified,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    PropertyNameCaseInsensitive = true,
    WriteIndented = false)]
[JsonSerializable(typeof(UserSettings))]
[JsonSerializable(typeof(WindowPreferences))]
[JsonSerializable(typeof(JavaCachePayload))]
[JsonSerializable(typeof(JavaCacheEntry))]
[JsonSerializable(typeof(List<LoaderVersion>))]
[JsonSerializable(typeof(IReadOnlyList<LoaderVersion>))]
[JsonSerializable(typeof(LoaderVersion))]
[JsonSerializable(typeof(List<ModListExportRow>))]
[JsonSerializable(typeof(ModListExportRow))]
[JsonSerializable(typeof(Dictionary<string, ModCacheEntry>))]
[JsonSerializable(typeof(ModCacheEntry))]
[JsonSerializable(typeof(Dictionary<string, ServerConfigPayload>))]
[JsonSerializable(typeof(ServerConfigPayload))]
[JsonSerializable(typeof(DeleteTombstoneRecord))]
[JsonSerializable(typeof(IReadOnlyList<LocalModInfo>))]
[JsonSerializable(typeof(List<LocalModInfo>))]
[JsonSerializable(typeof(LocalModInfo))]
[JsonSerializable(typeof(string[]))]
[JsonSerializable(typeof(List<string>))]
[JsonSerializable(typeof(ModrinthVersionFilesRequest))]
[JsonSerializable(typeof(List<ModJsonItem>))]
[JsonSerializable(typeof(ModJsonItem))]
[JsonSerializable(typeof(List<ServerUserCacheEntry>))]
[JsonSerializable(typeof(ServerUserCacheEntry))]
[JsonSerializable(typeof(List<ServerOperatorEntry>))]
[JsonSerializable(typeof(ServerOperatorEntry))]
[JsonSerializable(typeof(List<ServerWhitelistEntry>))]
[JsonSerializable(typeof(ServerWhitelistEntry))]
[JsonSerializable(typeof(List<ServerBannedPlayerEntry>))]
[JsonSerializable(typeof(ServerBannedPlayerEntry))]
[JsonSerializable(typeof(List<ServerBannedIpEntry>))]
[JsonSerializable(typeof(ServerBannedIpEntry))]
internal sealed partial class AppJsonSerializerContext : JsonSerializerContext;
