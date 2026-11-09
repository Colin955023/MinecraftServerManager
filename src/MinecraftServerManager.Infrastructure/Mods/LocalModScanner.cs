using MinecraftServerManager.Infrastructure.Logging;
using System.Collections.Concurrent;
using System.IO.Compression;
using System.Text.Json;
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
public sealed class LocalModScanner : ILocalModScanner
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LocalModScanner));
    private const int MaxMetadataEntryBytes = 256 * 1024;

    public async Task<IReadOnlyList<LocalModInfo>> ScanModsAsync(string modsDirectory, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        cancellationToken.ThrowIfCancellationRequested();

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        var entries = SafeFileSystem.ListBoundedDirectory(stableModsDir, rejectReparse: false)
            .Where(e => !e.IsDirectory && ModHelpers.IsModFileName(e.FullPath))
            .ToList();

        var persistence = new ModIndexPersistence(stableModsDir);
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

    private static async Task<LocalModInfo?> ScanSingleModCoreAsync(string filePath, ModIndexPersistence persistence, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        if (!SafeFileSystem.FileExists(filePath))
        {
            return null;
        }

        FileSystemMetadata fileInfo = SafeFileSystem.GetFileMetadata(filePath);
        string fileName = fileInfo.Name;
        bool isEnabled = !ModHelpers.IsDisabledModFileName(fileName);
        string baseStem = ModHelpers.ModFilenameStem(fileName);

        // 讀取快取（須檔案大小與最後修改時間皆相符）
        IReadOnlyDictionary<string, string>? cached = persistence.GetCachedMetadata(fileName, fileInfo.Length, fileInfo.LastWriteTimeUtc.Ticks);

        LocalModMetadataBuilder metadata;

        if (cached is not null && cached.TryGetValue("name", out string? cachedName) && !string.IsNullOrWhiteSpace(cachedName))
        {
            metadata = LocalModMetadataBuilder.FromDictionary(cached, baseStem);
        }
        else
        {
            metadata = ExtractMetadataFromJar(filePath, baseStem);
            ApplyFallbackLogic(baseStem, metadata);
            persistence.CacheMetadata(fileName, metadata.ToDictionary(), fileInfo.Length, fileInfo.LastWriteTimeUtc.Ticks);
        }

        // 計算或取得雜湊
        string? cachedHash = persistence.GetCachedHash(fileName, ModHelpers.PreferredHashAlgorithm);
        if (string.IsNullOrEmpty(cachedHash))
        {
            cachedHash = await HashCalculator.Shared.ComputeFileHashAsync(filePath, ModHelpers.PreferredHashAlgorithm, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrEmpty(cachedHash))
            {
                persistence.CacheHash(fileName, ModHelpers.PreferredHashAlgorithm, cachedHash);
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

        return modInfo;
    }

    private static LocalModMetadataBuilder ExtractMetadataFromJar(string filePath, string fallbackName)
    {
        var meta = new LocalModMetadataBuilder { Name = fallbackName };

        try
        {
            using var archive = SafeZipArchive.OpenRead(filePath);

            // 1. fabric.mod.json / quilt.mod.json
            var fabricEntry = archive.GetEntry("fabric.mod.json") ?? archive.GetEntry("quilt.mod.json");
            if (fabricEntry is not null && SafeZipArchive.ReadEntryTextBounded(fabricEntry, MaxMetadataEntryBytes) is { } fabricJson)
            {
                using var doc = JsonCodec.ParseDocument(fabricJson);
                ParseFabricJson(doc.RootElement, meta, archive);
                return meta;
            }

            // 2. META-INF/mods.toml / META-INF/neoforge.mods.toml (Forge / NeoForge)
            var forgeEntry = archive.GetEntry("META-INF/mods.toml") ?? archive.GetEntry("META-INF/neoforge.mods.toml");
            if (forgeEntry is not null && SafeZipArchive.ReadEntryTextBounded(forgeEntry, MaxMetadataEntryBytes) is { } content)
            {
                ParseForgeToml(content, meta, archive);
                return meta;
            }

            // 3. mcmod.info (Legacy Forge)
            var legacyEntry = archive.GetEntry("mcmod.info");
            if (legacyEntry is not null && SafeZipArchive.ReadEntryTextBounded(legacyEntry, MaxMetadataEntryBytes) is { } legacyJson)
            {
                using var doc = JsonCodec.ParseDocument(legacyJson);
                ParseLegacyMcModInfo(doc.RootElement, meta);
                return meta;
            }

            // 4. 檢查 MANIFEST.MF 與 Jar-in-Jar 內嵌模組 (例如 Sinytra Connector 等)
            if (TryExtractFromManifestOrJarJar(archive, meta))
            {
                return meta;
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("掃描模組封裝中繼資料異常: {0}", ex.Message);
        }

        return meta;
    }

    private static bool TryExtractFromManifestOrJarJar(ZipArchive archive, LocalModMetadataBuilder meta)
    {
        var manifest = ReadManifest(archive);
        string? manifestVersion = manifest.Version;

        // 優先從指定或搜尋到的內嵌 JAR 讀取 mods.toml / fabric.mod.json
        ZipArchiveEntry? innerJarEntry = null;
        if (!string.IsNullOrWhiteSpace(manifest.EmbeddedPath))
        {
            innerJarEntry = archive.GetEntry(manifest.EmbeddedPath.Replace('\\', '/'));
        }

        innerJarEntry ??= archive.Entries.FirstOrDefault(static e =>
            (e.FullName.StartsWith("META-INF/jarjar/", StringComparison.OrdinalIgnoreCase) ||
             e.FullName.StartsWith("META-INF/jars/", StringComparison.OrdinalIgnoreCase)) &&
            ModHelpers.IsJarFileName(e.FullName) &&
            e.Length <= 10 * 1024 * 1024);

        if (innerJarEntry is not null && SafeZipArchive.ReadEntryBytesBounded(innerJarEntry, 10 * 1024 * 1024) is { } innerJarBytes)
        {
            try
            {
                using var ms = new MemoryStream(innerJarBytes, writable: false);
                using var innerZip = SafeZipArchive.OpenRead(ms, leaveOpen: true, maxArchiveBytes: 10 * 1024 * 1024);

                bool parsed = false;
                var innerToml = innerZip.GetEntry("META-INF/mods.toml") ?? innerZip.GetEntry("META-INF/neoforge.mods.toml");
                var innerFabric = innerZip.GetEntry("fabric.mod.json") ?? innerZip.GetEntry("quilt.mod.json");
                if (innerToml is not null && SafeZipArchive.ReadEntryTextBounded(innerToml, MaxMetadataEntryBytes) is { } tomlContent)
                {
                    ParseForgeToml(tomlContent, meta, innerZip);
                    parsed = true;
                }
                else if (innerFabric is not null && SafeZipArchive.ReadEntryTextBounded(innerFabric, MaxMetadataEntryBytes) is { } innerFabricJson)
                {
                    using var doc = JsonCodec.ParseDocument(innerFabricJson);
                    ParseFabricJson(doc.RootElement, meta, innerZip);
                    parsed = true;
                }

                if (parsed)
                {
                    if (string.IsNullOrWhiteSpace(meta.Version) && !string.IsNullOrWhiteSpace(manifestVersion))
                    {
                        meta.Version = ModHelpers.StripColorAndFormattingCodes(manifestVersion);
                    }

                    return true;
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning("讀取內嵌 JAR 模組中繼資料異常: {0}", ex.Message);
            }
        }

        if (!string.IsNullOrWhiteSpace(manifest.Title))
        {
            meta.Name = ModHelpers.StripColorAndFormattingCodes(manifest.Title);
            if (!string.IsNullOrWhiteSpace(manifest.Vendor))
            {
                meta.Author = ModHelpers.StripColorAndFormattingCodes(manifest.Vendor);
            }
            if (!string.IsNullOrWhiteSpace(manifestVersion))
            {
                meta.Version = ModHelpers.StripColorAndFormattingCodes(manifestVersion);
            }
            return true;
        }

        return false;
    }

    private static void ParseFabricJson(JsonElement root, LocalModMetadataBuilder meta, ZipArchive archive)
    {
        meta.LoaderType = "fabric";
        if (root.TryGetProperty("id", out var idElem))
        {
            meta.Id = ModHelpers.StripColorAndFormattingCodes(idElem.GetString() ?? string.Empty);
        }

        if (root.TryGetProperty("name", out var nameElem))
        {
            meta.Name = ModHelpers.StripColorAndFormattingCodes(nameElem.GetString() ?? meta.Name);
        }

        if (root.TryGetProperty("version", out var verElem))
        {
            string? v = verElem.GetString() ?? meta.Version;
            if (v == "${file.jarVersion}")
            {
                v = ReadManifest(archive).Version ?? v;
            }

            if (!string.IsNullOrWhiteSpace(v))
            {
                meta.Version = ModHelpers.StripColorAndFormattingCodes(v);
            }
        }

        if (root.TryGetProperty("description", out var descElem))
        {
            meta.Description = ModHelpers.StripColorAndFormattingCodes(descElem.GetString() ?? string.Empty);
        }

        if (root.TryGetProperty("authors", out var authorsElem))
        {
            if (authorsElem.ValueKind == JsonValueKind.Array)
            {
                var authors = authorsElem.EnumerateArray()
                    .Select(static a => a.ValueKind == JsonValueKind.String ? a.GetString() : a.TryGetProperty("name", out var n) ? n.GetString() : null)
                    .Where(static a => !string.IsNullOrWhiteSpace(a))
                    .Select(ModHelpers.StripColorAndFormattingCodes);
                meta.Author = string.Join(", ", authors);
            }
            else if (authorsElem.ValueKind == JsonValueKind.String)
            {
                meta.Author = ModHelpers.StripColorAndFormattingCodes(authorsElem.GetString() ?? string.Empty);
            }
        }

        if (root.TryGetProperty("depends", out var dependsElem) &&
            dependsElem.TryGetProperty("minecraft", out var mcElem))
        {
            string? raw = null;
            if (mcElem.ValueKind == JsonValueKind.String)
            {
                raw = mcElem.GetString();
            }
            else if (mcElem.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in mcElem.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.String)
                    {
                        raw = item.GetString();
                        if (!string.IsNullOrWhiteSpace(raw))
                        {
                            break;
                        }
                    }
                }
            }

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

        int depIdx = content.IndexOf("[[dependencies", StringComparison.OrdinalIgnoreCase);
        string modSection = depIdx >= 0 ? content[..depIdx] : content;

        string? id = null;
        string? name = null;
        string? v = null;
        string? desc = null;
        string? author = null;

        int idx = 0;
        while (idx < modSection.Length)
        {
            int lineStart = idx;
            int nextNewline = modSection.IndexOf('\n', idx);
            int lineEnd = nextNewline >= 0 ? nextNewline : modSection.Length;

            int pos = lineStart;
            while (pos < lineEnd && (modSection[pos] == ' ' || modSection[pos] == '\t'))
            {
                pos++;
            }

            int eqIdx = -1;
            for (int i = pos; i < lineEnd; i++)
            {
                if (modSection[i] == '=')
                {
                    eqIdx = i;
                    break;
                }
            }

            if (eqIdx > pos)
            {
                ReadOnlySpan<char> keySpan = modSection.AsSpan(pos, eqIdx - pos).Trim();
                int nextIdx = lineEnd + (nextNewline >= 0 ? 1 : 0);
                string? parsedValue = ForgeTomlReader.ExtractValueAt(modSection, eqIdx + 1, ref nextIdx);
                if (parsedValue is not null)
                {
                    if (keySpan.Equals("modId", StringComparison.OrdinalIgnoreCase))
                    {
                        id ??= parsedValue;
                    }
                    else if (keySpan.Equals("displayName", StringComparison.OrdinalIgnoreCase))
                    {
                        name ??= parsedValue;
                    }
                    else if (keySpan.Equals("version", StringComparison.OrdinalIgnoreCase))
                    {
                        v ??= parsedValue;
                    }
                    else if (keySpan.Equals("description", StringComparison.OrdinalIgnoreCase))
                    {
                        desc ??= parsedValue;
                    }
                    else if (keySpan.Equals("authors", StringComparison.OrdinalIgnoreCase))
                    {
                        author ??= parsedValue;
                    }
                }

                idx = nextIdx;
                continue;
            }

            idx = lineEnd + (nextNewline >= 0 ? 1 : 0);
        }

        if (!string.IsNullOrWhiteSpace(id))
        {
            meta.Id = ModHelpers.StripColorAndFormattingCodes(id);
        }

        if (!string.IsNullOrWhiteSpace(name))
        {
            meta.Name = ModHelpers.StripColorAndFormattingCodes(name);
        }

        if (!string.IsNullOrWhiteSpace(v))
        {
            if (v == "${file.jarVersion}")
            {
                v = ReadManifest(archive).Version ?? v;
            }
            meta.Version = ModHelpers.StripColorAndFormattingCodes(v);
        }

        if (!string.IsNullOrWhiteSpace(desc))
        {
            meta.Description = ModHelpers.StripColorAndFormattingCodes(desc);
        }

        if (!string.IsNullOrWhiteSpace(author))
        {
            meta.Author = ModHelpers.StripColorAndFormattingCodes(author);
        }

        string? mcDepRange = ForgeTomlReader.ExtractMinecraftDependency(content);
        if (!string.IsNullOrWhiteSpace(mcDepRange))
        {
            string normalized = MinecraftVersionSemantics.NormalizeMinecraftVersion(mcDepRange);
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
            meta.Name = ModHelpers.StripColorAndFormattingCodes(nameElem.GetString() ?? meta.Name);
        }

        if (target.TryGetProperty("version", out var verElem))
        {
            string? v = verElem.GetString() ?? meta.Version;
            if (!string.IsNullOrWhiteSpace(v))
            {
                meta.Version = ModHelpers.StripColorAndFormattingCodes(v);
            }
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
            meta.Description = ModHelpers.StripColorAndFormattingCodes(descElem.GetString() ?? string.Empty);
        }

        if (target.TryGetProperty("authorList", out var authorListElem) && authorListElem.ValueKind == JsonValueKind.Array)
        {
            var authors = authorListElem.EnumerateArray()
                .Select(static a => a.GetString())
                .Where(static a => !string.IsNullOrWhiteSpace(a))
                .Select(ModHelpers.StripColorAndFormattingCodes);
            meta.Author = string.Join(", ", authors);
        }
    }

    private readonly record struct ManifestInfo(string? EmbeddedPath, string? Title, string? Vendor, string? Version);

    /// <summary>
    /// 讀取 META-INF/MANIFEST.MF 中與模組中繼資料相關的欄位（未展開之 <c>${projectversion}</c> 視為無版本）
    /// </summary>
    private static ManifestInfo ReadManifest(ZipArchive archive)
    {
        string? embeddedPath = null;
        string? title = null;
        string? vendor = null;
        string? version = null;

        try
        {
            var entry = archive.GetEntry("META-INF/MANIFEST.MF");
            if (entry is not null && SafeZipArchive.ReadEntryTextBounded(entry, MaxMetadataEntryBytes) is { } text)
            {
                foreach (ReadOnlySpan<char> line in text.AsSpan().EnumerateLines())
                {
                    int colon = line.IndexOf(':');
                    if (colon <= 0)
                    {
                        continue;
                    }

                    ReadOnlySpan<char> key = line[..colon].Trim();
                    ReadOnlySpan<char> val = line[(colon + 1)..].Trim();

                    if (key.Equals("Embedded-Dependencies-Mod", StringComparison.OrdinalIgnoreCase))
                    {
                        embeddedPath = val.ToString();
                    }
                    else if (key.Equals("Specification-Title", StringComparison.OrdinalIgnoreCase) ||
                             key.Equals("Implementation-Title", StringComparison.OrdinalIgnoreCase))
                    {
                        title ??= val.ToString();
                    }
                    else if (key.Equals("Specification-Vendor", StringComparison.OrdinalIgnoreCase) ||
                             key.Equals("Implementation-Vendor", StringComparison.OrdinalIgnoreCase))
                    {
                        vendor ??= val.ToString();
                    }
                    else if (key.Equals("Implementation-Version", StringComparison.OrdinalIgnoreCase) &&
                             !val.IsEmpty && !val.Equals("${projectversion}", StringComparison.Ordinal))
                    {
                        version ??= val.ToString();
                    }
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("讀取模組 MANIFEST.MF 異常: {0}", ex.Message);
        }

        return new ManifestInfo(embeddedPath, title, vendor, version);
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

            if (string.IsNullOrWhiteSpace(meta.Version))
            {
                ReadOnlySpan<char> span = baseStem.AsSpan();
                int currentPos = firstDash + 1;
                while (currentPos < span.Length)
                {
                    int nextDash = span[currentPos..].IndexOf('-');
                    ReadOnlySpan<char> part = nextDash >= 0 ? span.Slice(currentPos, nextDash) : span[currentPos..];
                    if (MemoryExtensions.ContainsAnyInRange(part, '0', '9'))
                    {
                        meta.Version = baseStem[currentPos..];
                        break;
                    }

                    if (nextDash < 0)
                    {
                        break;
                    }

                    currentPos += nextDash + 1;
                }
            }
        }
        else if (string.IsNullOrWhiteSpace(meta.Id))
        {
            meta.Id = baseStem;
        }

        if (string.IsNullOrWhiteSpace(meta.MinecraftVersion))
        {
            string? extracted = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(baseStem);
            if (!string.IsNullOrWhiteSpace(extracted))
            {
                meta.MinecraftVersion = extracted;
            }
        }

        if (string.IsNullOrWhiteSpace(meta.LoaderType))
        {
            string? detected = DetectLoaderDisplayNameFromText(baseStem);
            if (!string.IsNullOrEmpty(detected))
            {
                meta.LoaderType = detected;
            }
        }
    }

    private static string? DetectLoaderDisplayNameFromText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        if (text.Contains("neoforge", StringComparison.OrdinalIgnoreCase))
        {
            return "NeoForge";
        }

        if (text.Contains("fabric", StringComparison.OrdinalIgnoreCase))
        {
            return "Fabric";
        }

        if (text.Contains("quilt", StringComparison.OrdinalIgnoreCase))
        {
            return "Quilt";
        }

        if (text.Contains("forge", StringComparison.OrdinalIgnoreCase))
        {
            return "Forge";
        }

        return null;
    }

    private sealed class LocalModMetadataBuilder
    {
        public string Id { get; set; } = string.Empty;
        public string Name { get; set; } = string.Empty;
        public string? Version { get; set; }
        public string? MinecraftVersion { get; set; }
        public string? LoaderType { get; set; }
        public string Author { get; set; } = string.Empty;
        public string Description { get; set; } = string.Empty;
        public ModPlatform Platform { get; set; } = ModPlatform.Local;

        public Dictionary<string, string> ToDictionary() => new(StringComparer.OrdinalIgnoreCase)
        {
            ["id"] = Id,
            ["name"] = Name,
            ["version"] = Version ?? "未知",
            ["mc_version"] = MinecraftVersion ?? "未知",
            ["loader_type"] = LoaderType ?? "未知",
            ["author"] = Author,
            ["description"] = Description,
            ["platform"] = Platform.ToString(),
        };

        public static LocalModMetadataBuilder FromDictionary(IReadOnlyDictionary<string, string> dict, string fallbackName) => new()
        {
            Id = dict.GetValueOrDefault("id", string.Empty),
            Name = dict.GetValueOrDefault("name", fallbackName),
            Version = NormalizeUnknown(dict.TryGetValue("version", out string? v) ? v : null),
            MinecraftVersion = NormalizeUnknown(dict.TryGetValue("mc_version", out string? mc) ? mc : null),
            LoaderType = NormalizeUnknown(dict.TryGetValue("loader_type", out string? lt) ? lt : null),
            Author = dict.GetValueOrDefault("author", string.Empty),
            Description = dict.GetValueOrDefault("description", string.Empty),
            Platform = Enum.TryParse<ModPlatform>(dict.GetValueOrDefault("platform", "Local"), ignoreCase: true, out var p) ? p : ModPlatform.Local,
        };

        private static string? NormalizeUnknown(string? value)
        {
            if (string.IsNullOrWhiteSpace(value) || value == "未知" || string.Equals(value, "unknown", StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }

            return value.Trim();
        }

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
                version: Version ?? "未知",
                minecraftVersion: MinecraftVersion ?? "未知",
                loaderType: LoaderType ?? "未知",
                description: Description,
                author: Author,
                platform: Platform,
                status: isEnabled ? ModStatus.Enabled : ModStatus.Disabled,
                filePath: filePath,
                fileSize: fileSize,
                fileMtime: fileMtime,
                currentHash: cachedHash ?? string.Empty,
                hashAlgorithm: string.IsNullOrEmpty(cachedHash) ? string.Empty : ModHelpers.PreferredHashAlgorithm);
    }
}
