using System.Text.Json.Serialization;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Services;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.Infrastructure.Serialization;

/// <summary>System.Text.Json 來源產生器內容；只登錄 <c>JsonCodec</c> 直接序列化的型別（其成員型別自動產生中繼資料）。命名、縮排與大小寫規則由 <c>JsonCodec</c> 傳入的選項決定</summary>
[JsonSerializable(typeof(UserSettings))]
[JsonSerializable(typeof(List<Core.Ports.TrackedServerProcess>))]
[JsonSerializable(typeof(JavaCachePayload))]
[JsonSerializable(typeof(List<LoaderVersion>))]
[JsonSerializable(typeof(IReadOnlyList<LoaderVersion>))]
[JsonSerializable(typeof(Dictionary<string, ModCacheEntry>))]
[JsonSerializable(typeof(Dictionary<string, ServerConfigPayload>))]
[JsonSerializable(typeof(DeleteTombstoneRecord))]
[JsonSerializable(typeof(string[]))]
[JsonSerializable(typeof(string[][]))]
[JsonSerializable(typeof(ModrinthVersionFilesRequest))]
[JsonSerializable(typeof(GitHubReleasePayload))]
[JsonSerializable(typeof(List<ModJsonItem>))]
[JsonSerializable(typeof(List<ServerUserCacheEntry>))]
[JsonSerializable(typeof(List<ServerOperatorEntry>))]
[JsonSerializable(typeof(List<ServerWhitelistEntry>))]
[JsonSerializable(typeof(List<ServerBannedPlayerEntry>))]
[JsonSerializable(typeof(List<ServerBannedIpEntry>))]
internal sealed partial class AppJsonSerializerContext : JsonSerializerContext;
