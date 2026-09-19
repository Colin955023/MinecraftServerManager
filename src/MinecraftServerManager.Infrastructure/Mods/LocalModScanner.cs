using System.Collections.Concurrent;
using System.IO.Compression;
using System.Text.Json;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// 本地模組目錄掃描器與 JAR 詮釋資料抽取實作
/// </summary>
public sealed partial class LocalModScanner(IModIndexPersistence? indexPersistence = null) : ILocalModScanner
{
    private const long MaxMetadataEntryBytes = 2 * 1024 * 1024;

    public async Task<IReadOnlyList<LocalModInfo>> ScanModsAsync(string modsDirectory, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        cancellationToken.ThrowIfCancellationRequested();

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        var entries = SafeFileSystem.ListBoundedDirectory(stableModsDir, rejectReparse: false)
            .Where(e => !e.IsDirectory && (e.FullPath.EndsWith(".jar", StringComparison.OrdinalIgnoreCase) ||
                                          e.FullPath.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase)))
            .OrderBy(e => Path.GetFileName(e.FullPath), StringComparer.OrdinalIgnoreCase)
            .ToList();

        var persistence = indexPersistence ?? new ModIndexPersistence(stableModsDir);
        var fileNames = entries.Select(e => Path.GetFileName(e.FullPath)).ToList();
        persistence.CleanupStaleEntries(fileNames);

        var result = new ConcurrentBag<LocalModInfo>();
        var parallelOptions = new ParallelOptions
        {
            MaxDegreeOfParallelism = Math.Max(1, Environment.ProcessorCount),
            CancellationToken = cancellationToken
        };

        await Parallel.ForEachAsync(entries, parallelOptions, async (entry, ct) =>
        {
            var mod = await ScanSingleModCoreAsync(entry.FullPath, persistence, ct).ConfigureAwait(false);
            if (mod is not null)
            {
                result.Add(mod);
            }
        }).ConfigureAwait(false);

        persistence.Flush();
        return result.OrderBy(m => m.Filename, StringComparer.OrdinalIgnoreCase).ToList();
    }

    public Task<LocalModInfo?> ScanSingleModAsync(string filePath, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(filePath);
        cancellationToken.ThrowIfCancellationRequested();

        string dir = Path.GetDirectoryName(filePath) ?? string.Empty;
        var persistence = indexPersistence ?? (!string.IsNullOrEmpty(dir) ? new ModIndexPersistence(dir) : null);
        return ScanSingleModCoreAsync(filePath, persistence, cancellationToken);
    }

    private static Task<LocalModInfo?> ScanSingleModCoreAsync(string filePath, IModIndexPersistence? persistence, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        if (!File.Exists(filePath))
        {
            return Task.FromResult<LocalModInfo?>(null);
        }

        var fileInfo = new FileInfo(filePath);
        string fileName = fileInfo.Name;
        bool isEnabled = !fileName.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase);
        string baseStem = ModHelpers.ModFilenameStem(fileName);

        // 讀取快取
        var cached = persistence?.GetCachedMetadata(fileName);
        LocalModMetadataBuilder metadata;

        if (cached is not null && cached.TryGetValue("name", out string? cachedName) && !string.IsNullOrWhiteSpace(cachedName))
        {
            metadata = LocalModMetadataBuilder.FromDictionary(cached, baseStem);
        }
        else
        {
            metadata = ExtractMetadataFromJar(filePath, baseStem);
            ApplyFallbackLogic(baseStem, metadata);
            persistence?.CacheMetadata(fileName, metadata.ToDictionary());
        }

        // 計算或取得雜湊
        string? cachedHash = persistence?.GetCachedHash(fileName, ModHelpers.PreferredHashAlgorithm);
        if (string.IsNullOrEmpty(cachedHash))
        {
            cachedHash = HashCalculator.Shared.ComputeFileHash(filePath, ModHelpers.PreferredHashAlgorithm);
            if (!string.IsNullOrEmpty(cachedHash))
            {
                persistence?.CacheHash(fileName, ModHelpers.PreferredHashAlgorithm, cachedHash);
            }
        }

        var modInfo = metadata.ToModInfo(
            filePath: filePath,
            fileName: fileName,
            baseStem: baseStem,
            fileSize: fileInfo.Length,
            fileMtime: fileInfo.LastWriteTimeUtc.Subtract(DateTime.UnixEpoch).TotalSeconds,
            isEnabled: isEnabled,
            cachedHash: cachedHash);

        return Task.FromResult<LocalModInfo?>(modInfo);
    }

    private static LocalModMetadataBuilder ExtractMetadataFromJar(string filePath, string fallbackName)
    {
        var meta = new LocalModMetadataBuilder { Name = fallbackName };

        try
        {
            using var archive = ZipFile.OpenRead(filePath);

            // 1. fabric.mod.json / quilt.mod.json
            var fabricEntry = archive.GetEntry("fabric.mod.json") ?? archive.GetEntry("quilt.mod.json");
            if (fabricEntry is not null && fabricEntry.Length <= MaxMetadataEntryBytes)
            {
                using var stream = fabricEntry.Open();
                using var doc = JsonDocument.Parse(stream);
                ParseFabricJson(doc.RootElement, meta, archive);
                return meta;
            }

            // 2. META-INF/mods.toml (Forge / NeoForge)
            var forgeEntry = archive.GetEntry("META-INF/mods.toml");
            if (forgeEntry is not null && forgeEntry.Length <= MaxMetadataEntryBytes)
            {
                using var stream = forgeEntry.Open();
                using var reader = new StreamReader(stream);
                string content = reader.ReadToEnd();
                ParseForgeToml(content, meta, archive);
                return meta;
            }

            // 3. mcmod.info (Legacy Forge)
            var legacyEntry = archive.GetEntry("mcmod.info");
            if (legacyEntry is not null && legacyEntry.Length <= MaxMetadataEntryBytes)
            {
                using var stream = legacyEntry.Open();
                using var doc = JsonDocument.Parse(stream);
                ParseLegacyMcModInfo(doc.RootElement, meta);
                return meta;
            }
        }
        catch
        {
        }

        return meta;
    }

    private static void ParseFabricJson(JsonElement root, LocalModMetadataBuilder meta, ZipArchive archive)
    {
        meta.LoaderType = "fabric";
        if (root.TryGetProperty("id", out var idElem))
        {
            meta.Id = idElem.GetString() ?? string.Empty;
        }

        if (root.TryGetProperty("name", out var nameElem))
        {
            meta.Name = nameElem.GetString() ?? meta.Name;
        }

        if (root.TryGetProperty("version", out var verElem))
        {
            string v = verElem.GetString() ?? meta.Version;
            if (v == "${file.jarVersion}")
            {
                v = ReadManifestVersion(archive) ?? v;
            }
            meta.Version = v;
        }

        if (root.TryGetProperty("description", out var descElem))
        {
            meta.Description = descElem.GetString() ?? string.Empty;
        }

        if (root.TryGetProperty("authors", out var authorsElem))
        {
            if (authorsElem.ValueKind == JsonValueKind.Array)
            {
                var authors = authorsElem.EnumerateArray()
                    .Select(a => a.ValueKind == JsonValueKind.String ? a.GetString() : a.TryGetProperty("name", out var n) ? n.GetString() : null)
                    .Where(a => !string.IsNullOrWhiteSpace(a));
                meta.Author = string.Join(", ", authors);
            }
            else if (authorsElem.ValueKind == JsonValueKind.String)
            {
                meta.Author = authorsElem.GetString() ?? string.Empty;
            }
        }

        if (root.TryGetProperty("depends", out var dependsElem) &&
            dependsElem.TryGetProperty("minecraft", out var mcElem))
        {
            string? raw = mcElem.GetString();
            if (!string.IsNullOrWhiteSpace(raw))
            {
                string normalized = MinecraftVersionSemantics.NormalizeMinecraftVersion(raw);
                if (!string.IsNullOrWhiteSpace(normalized))
                {
                    meta.MinecraftVersion = normalized;
                }
            }
        }
    }

    private static void ParseForgeToml(string content, LocalModMetadataBuilder meta, ZipArchive archive)
    {
        meta.LoaderType = "forge";

        var idMatch = ForgeModIdRegex().Match(content);
        if (idMatch.Success)
        {
            meta.Id = idMatch.Groups[1].Value.Trim('\'', '"', ' ', '\r', '\n');
        }

        var nameMatch = ForgeDisplayNameRegex().Match(content);
        if (nameMatch.Success)
        {
            meta.Name = nameMatch.Groups[1].Value.Trim('\'', '"', ' ', '\r', '\n');
        }

        var verMatch = ForgeVersionRegex().Match(content);
        if (verMatch.Success)
        {
            string v = verMatch.Groups[1].Value.Trim('\'', '"', ' ', '\r', '\n');
            if (v == "${file.jarVersion}")
            {
                v = ReadManifestVersion(archive) ?? v;
            }
            meta.Version = v;
        }

        var descMatch = ForgeDescRegex().Match(content);
        if (descMatch.Success)
        {
            meta.Description = descMatch.Groups[1].Value.Trim('\'', '"', ' ', '\r', '\n');
        }

        var authorMatch = ForgeAuthorsRegex().Match(content);
        if (authorMatch.Success)
        {
            meta.Author = authorMatch.Groups[1].Value.Trim('\'', '"', ' ', '\r', '\n');
        }

        var mcVerMatch = ForgeMcDepRegex().Match(content);
        if (mcVerMatch.Success)
        {
            string raw = mcVerMatch.Groups[1].Value.Trim('\'', '"', ' ', '\r', '\n');
            string normalized = MinecraftVersionSemantics.NormalizeMinecraftVersion(raw);
            if (!string.IsNullOrWhiteSpace(normalized))
            {
                meta.MinecraftVersion = normalized;
            }
        }
    }

    private static void ParseLegacyMcModInfo(JsonElement root, LocalModMetadataBuilder meta)
    {
        meta.LoaderType = "Forge";
        var target = root;
        if (root.ValueKind == JsonValueKind.Array && root.GetArrayLength() > 0)
        {
            target = root[0];
        }

        if (target.TryGetProperty("name", out var nameElem))
        {
            meta.Name = nameElem.GetString() ?? meta.Name;
        }

        if (target.TryGetProperty("version", out var verElem))
        {
            meta.Version = verElem.GetString() ?? meta.Version;
        }

        if (target.TryGetProperty("mcversion", out var mcElem))
        {
            string? raw = mcElem.GetString();
            if (!string.IsNullOrWhiteSpace(raw))
            {
                string normalized = MinecraftVersionSemantics.NormalizeMinecraftVersion(raw);
                if (!string.IsNullOrWhiteSpace(normalized))
                {
                    meta.MinecraftVersion = normalized;
                }
            }
        }

        if (target.TryGetProperty("description", out var descElem))
        {
            meta.Description = descElem.GetString() ?? string.Empty;
        }

        if (target.TryGetProperty("authorList", out var authorListElem) && authorListElem.ValueKind == JsonValueKind.Array)
        {
            var authors = authorListElem.EnumerateArray().Select(a => a.GetString()).Where(a => !string.IsNullOrWhiteSpace(a));
            meta.Author = string.Join(", ", authors);
        }
    }

    private static string? ReadManifestVersion(ZipArchive archive)
    {
        try
        {
            var manifestEntry = archive.GetEntry("META-INF/MANIFEST.MF");
            if (manifestEntry is null)
            {
                return null;
            }

            using var stream = manifestEntry.Open();
            using var reader = new StreamReader(stream);
            string? line;
            while ((line = reader.ReadLine()) is not null)
            {
                if (line.StartsWith("Implementation-Version:", StringComparison.OrdinalIgnoreCase))
                {
                    string val = line.Split(':', 2)[1].Trim();
                    if (!string.IsNullOrEmpty(val) && val != "${projectversion}")
                    {
                        return val;
                    }
                }
            }
        }
        catch
        {
        }
        return null;
    }

    private static void ApplyFallbackLogic(string baseStem, LocalModMetadataBuilder meta)
    {
        if (meta.Name == baseStem || string.IsNullOrWhiteSpace(meta.Name))
        {
            meta.Name = ModHelpers.NormalizeModSearchQuery(baseStem);
            if (string.IsNullOrWhiteSpace(meta.Name))
            {
                meta.Name = baseStem;
            }
        }

        if (meta.Version == "未知" || string.IsNullOrWhiteSpace(meta.Version))
        {
            string[] parts = baseStem.Split('-');
            if (parts.Length > 1)
            {
                for (int i = 1; i < parts.Length; i++)
                {
                    if (parts[i].Any(char.IsDigit))
                    {
                        meta.Version = string.Join('-', parts[i..]);
                        break;
                    }
                }
            }
        }

        if (meta.MinecraftVersion == "未知" || string.IsNullOrWhiteSpace(meta.MinecraftVersion))
        {
            string? extracted = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(baseStem);
            if (!string.IsNullOrWhiteSpace(extracted))
            {
                meta.MinecraftVersion = extracted;
            }
        }

        if (meta.LoaderType == "未知")
        {
            string detected = MinecraftVersionSemantics.DetectLoaderFromText(baseStem);
            if (detected != "unknown")
            {
                meta.LoaderType = detected switch
                {
                    "fabric" => "Fabric",
                    "neoforge" => "NeoForge",
                    "quilt" => "Quilt",
                    "forge" => "Forge",
                    _ => meta.LoaderType,
                };
            }
        }

        if (string.IsNullOrWhiteSpace(meta.Id))
        {
            string[] parts = baseStem.Split('-');
            meta.Id = parts.Length > 0 && !string.IsNullOrWhiteSpace(parts[0]) ? parts[0] : baseStem;
        }
    }

    private sealed class LocalModMetadataBuilder
    {
        public string Id { get; set; } = string.Empty;
        public string Name { get; set; } = string.Empty;
        public string Version { get; set; } = "未知";
        public string MinecraftVersion { get; set; } = "未知";
        public string LoaderType { get; set; } = "未知";
        public string Author { get; set; } = string.Empty;
        public string Description { get; set; } = string.Empty;

        public Dictionary<string, string> ToDictionary() => new(StringComparer.OrdinalIgnoreCase)
        {
            ["id"] = Id,
            ["name"] = Name,
            ["version"] = Version,
            ["mc_version"] = MinecraftVersion,
            ["loader_type"] = LoaderType,
            ["author"] = Author,
            ["description"] = Description,
        };

        public static LocalModMetadataBuilder FromDictionary(IReadOnlyDictionary<string, string> dict, string fallbackName) => new()
        {
            Id = dict.GetValueOrDefault("id", string.Empty),
            Name = dict.GetValueOrDefault("name", fallbackName),
            Version = dict.GetValueOrDefault("version", "未知"),
            MinecraftVersion = dict.GetValueOrDefault("mc_version", "未知"),
            LoaderType = dict.GetValueOrDefault("loader_type", "未知"),
            Author = dict.GetValueOrDefault("author", string.Empty),
            Description = dict.GetValueOrDefault("description", string.Empty),
        };

        public LocalModInfo ToModInfo(
            string filePath,
            string fileName,
            string baseStem,
            long fileSize,
            double fileMtime,
            bool isEnabled,
            string? cachedHash) =>
            new(
                id: string.IsNullOrWhiteSpace(Id) ? baseStem : Id,
                name: string.IsNullOrWhiteSpace(Name) ? baseStem : Name,
                filename: fileName,
                version: string.IsNullOrWhiteSpace(Version) ? "未知" : Version,
                minecraftVersion: string.IsNullOrWhiteSpace(MinecraftVersion) ? "未知" : MinecraftVersion,
                loaderType: string.IsNullOrWhiteSpace(LoaderType) ? "未知" : LoaderType,
                description: Description ?? string.Empty,
                author: Author ?? string.Empty,
                platform: ModPlatform.Local,
                status: isEnabled ? ModStatus.Enabled : ModStatus.Disabled,
                filePath: filePath,
                fileSize: fileSize,
                fileMtime: fileMtime,
                currentHash: cachedHash ?? string.Empty,
                hashAlgorithm: string.IsNullOrEmpty(cachedHash) ? string.Empty : ModHelpers.PreferredHashAlgorithm);
    }

    [GeneratedRegex(@"(?m)^\s*modId\s*=\s*(.+)$")]
    private static partial Regex ForgeModIdRegex();

    [GeneratedRegex(@"(?m)^\s*displayName\s*=\s*(.+)$")]
    private static partial Regex ForgeDisplayNameRegex();

    [GeneratedRegex(@"(?m)^\s*version\s*=\s*(.+)$")]
    private static partial Regex ForgeVersionRegex();

    [GeneratedRegex(@"(?m)^\s*description\s*=\s*(.+)$")]
    private static partial Regex ForgeDescRegex();

    [GeneratedRegex(@"(?m)^\s*authors\s*=\s*(.+)$")]
    private static partial Regex ForgeAuthorsRegex();

    [GeneratedRegex(@"(?m)^\s*modId\s*=\s*[""']minecraft[""']\s*\n\s*versionRange\s*=\s*(.+)$")]
    private static partial Regex ForgeMcDepRegex();
}
