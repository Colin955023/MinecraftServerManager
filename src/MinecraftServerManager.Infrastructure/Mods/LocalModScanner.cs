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
        return [.. result.OrderBy(m => m.Filename, StringComparer.OrdinalIgnoreCase)];
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

        string id = ExtractTomlString(content, "modId");
        if (!string.IsNullOrWhiteSpace(id))
        {
            meta.Id = id;
        }

        string name = ExtractTomlString(content, "displayName");
        if (!string.IsNullOrWhiteSpace(name))
        {
            meta.Name = name;
        }

        string v = ExtractTomlString(content, "version");
        if (!string.IsNullOrWhiteSpace(v))
        {
            if (v == "${file.jarVersion}")
            {
                v = ReadManifestVersion(archive) ?? v;
            }
            meta.Version = v;
        }

        string desc = ExtractTomlString(content, "description");
        if (!string.IsNullOrWhiteSpace(desc))
        {
            meta.Description = desc;
        }

        string author = ExtractTomlString(content, "authors");
        if (!string.IsNullOrWhiteSpace(author))
        {
            meta.Author = author;
        }

        var mcVerMatch = ForgeMcDepRegex().Match(content);
        if (mcVerMatch.Success)
        {
            string raw = CleanTomlValue(mcVerMatch.Groups[1].Value);
            string normalized = MinecraftVersionSemantics.NormalizeMinecraftVersion(raw);
            if (!string.IsNullOrWhiteSpace(normalized))
            {
                meta.MinecraftVersion = normalized;
            }
        }
    }

    private static string ExtractTomlString(string content, string key)
    {
        if (string.IsNullOrWhiteSpace(content))
        {
            return string.Empty;
        }

        int idx = 0;
        while (idx < content.Length)
        {
            int lineStart = idx;
            int nextNewline = content.IndexOf('\n', idx);
            int lineEnd = nextNewline >= 0 ? nextNewline : content.Length;

            int pos = lineStart;
            while (pos < lineEnd && (content[pos] == ' ' || content[pos] == '\t'))
            {
                pos++;
            }

            if (pos + key.Length < lineEnd &&
                content.AsSpan(pos, key.Length).Equals(key, StringComparison.OrdinalIgnoreCase))
            {
                pos += key.Length;
                while (pos < lineEnd && (content[pos] == ' ' || content[pos] == '\t'))
                {
                    pos++;
                }

                if (pos < lineEnd && content[pos] == '=')
                {
                    pos++;
                    while (pos < content.Length && (content[pos] == ' ' || content[pos] == '\t' || content[pos] == '\r' || content[pos] == '\n'))
                    {
                        pos++;
                    }

                    if (pos >= content.Length)
                    {
                        return string.Empty;
                    }

                    if (pos + 3 <= content.Length && content.AsSpan(pos, 3).SequenceEqual("'''"))
                    {
                        int end = content.IndexOf("'''", pos + 3, StringComparison.Ordinal);
                        return end >= 0 ? content[(pos + 3)..end].Trim() : content[(pos + 3)..].Trim();
                    }

                    if (pos + 3 <= content.Length && content.AsSpan(pos, 3).SequenceEqual("\"\"\""))
                    {
                        int end = content.IndexOf("\"\"\"", pos + 3, StringComparison.Ordinal);
                        return end >= 0 ? content[(pos + 3)..end].Trim() : content[(pos + 3)..].Trim();
                    }

                    if (content[pos] == '\'')
                    {
                        int end = content.IndexOf('\'', pos + 1);
                        return end >= 0 ? content[(pos + 1)..end].Trim() : content[(pos + 1)..].Trim();
                    }

                    if (content[pos] == '"')
                    {
                        int end = -1;
                        for (int i = pos + 1; i < content.Length; i++)
                        {
                            if (content[i] == '"' && content[i - 1] != '\\')
                            {
                                end = i;
                                break;
                            }
                        }
                        return end >= 0 ? content[(pos + 1)..end].Trim() : content[(pos + 1)..].Trim();
                    }

                    int eol = content.IndexOf('\n', pos);
                    string rawVal = eol >= 0 ? content[pos..eol] : content[pos..];
                    int hashIdx = rawVal.IndexOf('#');
                    if (hashIdx >= 0)
                    {
                        rawVal = rawVal[..hashIdx];
                    }
                    return rawVal.Trim();
                }
            }

            if (nextNewline < 0)
            {
                break;
            }
            idx = nextNewline + 1;
        }

        return string.Empty;
    }

    private static string CleanTomlValue(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return string.Empty;
        }

        string val = raw.Trim();
        bool inQuotes = false;
        char quoteChar = '\0';
        int commentIndex = -1;
        for (int i = 0; i < val.Length; i++)
        {
            char c = val[i];
            if ((c == '"' || c == '\'') && (i == 0 || val[i - 1] != '\\'))
            {
                if (!inQuotes)
                {
                    inQuotes = true;
                    quoteChar = c;
                }
                else if (c == quoteChar)
                {
                    inQuotes = false;
                }
            }
            else if (c == '#' && !inQuotes)
            {
                commentIndex = i;
                break;
            }
        }

        if (commentIndex >= 0)
        {
            val = val[..commentIndex];
        }

        return val.Trim('\'', '"', ' ', '\r', '\n', '\t');
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
            var authors = authorListElem.EnumerateArray().Select(static a => a.GetString()).Where(static a => !string.IsNullOrWhiteSpace(a));
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
                    int colonIdx = line.IndexOf(':');
                    if (colonIdx >= 0)
                    {
                        string val = line[(colonIdx + 1)..].Trim();
                        if (!string.IsNullOrEmpty(val) && val != "${projectversion}")
                        {
                            return val;
                        }
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

        int firstDash = baseStem.IndexOf('-');
        if (firstDash > 0)
        {
            if (string.IsNullOrWhiteSpace(meta.Id))
            {
                meta.Id = baseStem[..firstDash];
            }

            if (meta.Version == "未知" || string.IsNullOrWhiteSpace(meta.Version))
            {
                string[] parts = baseStem.Split('-');
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
        else if (string.IsNullOrWhiteSpace(meta.Id))
        {
            meta.Id = baseStem;
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
        public ModPlatform Platform { get; set; } = ModPlatform.Local;

        public Dictionary<string, string> ToDictionary() => new(StringComparer.OrdinalIgnoreCase)
        {
            ["id"] = Id,
            ["name"] = Name,
            ["version"] = Version,
            ["mc_version"] = MinecraftVersion,
            ["loader_type"] = LoaderType,
            ["author"] = Author,
            ["description"] = Description,
            ["platform"] = Platform.ToString(),
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
            Platform = Enum.TryParse<ModPlatform>(dict.GetValueOrDefault("platform", "Local"), ignoreCase: true, out var p) ? p : ModPlatform.Local,
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
                platform: Platform,
                status: isEnabled ? ModStatus.Enabled : ModStatus.Disabled,
                filePath: filePath,
                fileSize: fileSize,
                fileMtime: fileMtime,
                currentHash: cachedHash ?? string.Empty,
                hashAlgorithm: string.IsNullOrEmpty(cachedHash) ? string.Empty : ModHelpers.PreferredHashAlgorithm);
    }

    [GeneratedRegex(@"(?m)^\s*modId\s*=\s*[""']minecraft[""']\s*\n\s*versionRange\s*=\s*(.+)$")]
    private static partial Regex ForgeMcDepRegex();
}
