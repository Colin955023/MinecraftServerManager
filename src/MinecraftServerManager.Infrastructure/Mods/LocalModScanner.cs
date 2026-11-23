using System.IO.Compression;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

public sealed partial class LocalModScanner : ILocalModScanner
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LocalModScanner));
    private const int MaxMetadataEntryBytes = 256 * 1024;

    /// <summary>內嵌 JAR（jarjar／jars）與其 ZIP 解析的位元組上限</summary>
    private const int MaxEmbeddedJarBytes = 10 * 1024 * 1024;

    // 同目錄掃描共用 .modcache 索引檔，須序列化避免互相覆寫
    private readonly KeyedAsyncLock _directoryGates = new();

    public async Task<IReadOnlyList<LocalModInfo>> ScanModsAsync(string modsDirectory, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modsDirectory);
        cancellationToken.ThrowIfCancellationRequested();

        string stableModsDir = SafeFileSystem.ResolveStableDirectory(modsDirectory, create: true);
        using var gate = await _directoryGates.AcquireAsync(stableModsDir, cancellationToken).ConfigureAwait(false);
        var entries = SafeFileSystem.ListBoundedDirectory(stableModsDir, rejectReparse: false)
            .Where(static e => !e.IsDirectory && ModHelpers.IsModFileName(e.FullPath))
            .ToList();

        var persistence = new ModIndexPersistence(stableModsDir);
        persistence.CleanupStaleEntries(entries.Select(static e => Path.GetFileName(e.FullPath)));

        // 平行掃描上限設為 4，避免磁碟 I/O 與 CPU 爭搶；各項結果依索引寫入陣列，免去並行集合
        var scanned = new LocalModInfo?[entries.Count];
        await Parallel.ForAsync(0, entries.Count, new ParallelOptions { MaxDegreeOfParallelism = 4, CancellationToken = cancellationToken }, async (i, ct) =>
            scanned[i] = await ScanSingleModAsync(entries[i], persistence, ct).ConfigureAwait(false)).ConfigureAwait(false);

        persistence.Flush();
        return [.. scanned.OfType<LocalModInfo>().OrderBy(static m => m.FileName, StringComparer.OrdinalIgnoreCase)];
    }

    /// <summary>單一模組失敗只略過該筆，不中斷整體掃描</summary>
    private static async Task<LocalModInfo?> ScanSingleModAsync(FileSystemEntry entry, ModIndexPersistence persistence, CancellationToken cancellationToken)
    {
        try
        {
            return await ScanSingleModCoreAsync(entry, persistence, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "掃描模組檔案失敗，已略過: {File}", entry.FullPath);
            return null;
        }
    }

    private static async Task<LocalModInfo?> ScanSingleModCoreAsync(FileSystemEntry entry, ModIndexPersistence persistence, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        string filePath = entry.FullPath;
        string fileName = Path.GetFileName(filePath);
        long fileLength = entry.Length;
        long lastWriteTicks = entry.LastWriteTimeUtc.Ticks;
        bool isEnabled = !ModHelpers.IsDisabledModFileName(fileName);
        string baseStem = ModHelpers.ModFilenameStem(fileName);

        // 讀取快取（須檔案大小與最後修改時間皆相符）
        IReadOnlyDictionary<string, string>? cached = persistence.GetCachedMetadata(fileName, fileLength, lastWriteTicks);

        LocalModMetadataBuilder metadata;

        if (cached is not null && cached.TryGetValue("name", out string? cachedName) && !string.IsNullOrWhiteSpace(cachedName))
        {
            metadata = LocalModMetadataBuilder.FromDictionary(cached, baseStem);
        }
        else
        {
            metadata = ExtractMetadataFromJar(filePath, baseStem);
            ApplyFallbackLogic(baseStem, metadata);
            persistence.CacheMetadata(fileName, metadata.ToDictionary(), fileLength, lastWriteTicks);
        }

        // 計算或取得雜湊
        string? cachedHash = persistence.GetCachedHash(fileName, ModHelpers.PreferredHashAlgorithm);
        if (string.IsNullOrEmpty(cachedHash))
        {
            try
            {
                cachedHash = await HashCalculator.ComputeFileHashAsync(filePath, ModHelpers.PreferredHashAlgorithm, cancellationToken: cancellationToken).ConfigureAwait(false);
                if (!string.IsNullOrEmpty(cachedHash))
                {
                    persistence.CacheHash(fileName, ModHelpers.PreferredHashAlgorithm, cachedHash);
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                // 檔案被占用時仍列出模組，僅缺雜湊
                Logger.Warning(ex, "計算模組雜湊失敗: {File}", fileName);
                cachedHash = null;
            }
        }

        var modInfo = metadata.ToModInfo(
            fileName: fileName,
            baseStem: baseStem,
            fileSize: fileLength,
            fileMtime: entry.LastWriteTimeUtc.Subtract(DateTime.UnixEpoch).TotalSeconds,
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

            // 1~2. fabric.mod.json / quilt.mod.json / mods.toml / neoforge.mods.toml
            if (TryParseModDescriptor(archive, meta))
            {
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
            Logger.Warning(ex, "掃描模組封裝中繼資料失敗");
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
            e.Length <= MaxEmbeddedJarBytes);

        if (innerJarEntry is not null && SafeZipArchive.ReadEntryBytesBounded(innerJarEntry, MaxEmbeddedJarBytes) is { } innerJarBytes)
        {
            try
            {
                using var ms = new MemoryStream(innerJarBytes, writable: false);
                using var innerZip = SafeZipArchive.OpenRead(ms, leaveOpen: true, maxArchiveBytes: MaxEmbeddedJarBytes);

                if (TryParseModDescriptor(innerZip, meta))
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
                Logger.Warning(ex, "讀取內嵌 JAR 模組中繼資料失敗");
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

    /// <summary>依序解析 fabric.mod.json、quilt.mod.json、mods.toml、neoforge.mods.toml；成功解析任一者回傳 true</summary>
    private static bool TryParseModDescriptor(ZipArchive archive, LocalModMetadataBuilder meta)
    {
        if (archive.GetEntry("fabric.mod.json") is { } fabricEntry && SafeZipArchive.ReadEntryTextBounded(fabricEntry, MaxMetadataEntryBytes) is { } fabricJson)
        {
            using var doc = JsonCodec.ParseDocument(fabricJson);
            ParseFabricJson(doc.RootElement, meta, archive);
            return true;
        }

        if (archive.GetEntry("quilt.mod.json") is { } quiltEntry && SafeZipArchive.ReadEntryTextBounded(quiltEntry, MaxMetadataEntryBytes) is { } quiltJson)
        {
            using var doc = JsonCodec.ParseDocument(quiltJson);
            ParseQuiltJson(doc.RootElement, meta, archive);
            return true;
        }

        if (archive.GetEntry("META-INF/neoforge.mods.toml") is { } neoEntry && SafeZipArchive.ReadEntryTextBounded(neoEntry, MaxMetadataEntryBytes) is { } neoToml)
        {
            ParseForgeToml(neoToml, meta, archive, LoaderNeoForge);
            return true;
        }

        if (archive.GetEntry("META-INF/mods.toml") is { } forgeEntry && SafeZipArchive.ReadEntryTextBounded(forgeEntry, MaxMetadataEntryBytes) is { } forgeToml)
        {
            ParseForgeToml(forgeToml, meta, archive, LoaderForge);
            return true;
        }

        return false;
    }

    // 載入器顯示名稱統一大小寫
    private const string LoaderFabric = "Fabric";
    private const string LoaderQuilt = "Quilt";
    private const string LoaderForge = "Forge";
    private const string LoaderNeoForge = "NeoForge";

    private static readonly string[] KnownLoaderDisplayNames = [LoaderNeoForge, LoaderFabric, LoaderQuilt, LoaderForge];

    /// <summary>將載入器名稱正規化為統一大小寫的顯示名稱；未知名稱原樣回傳</summary>
    private static string NormalizeLoaderDisplayName(string loader)
    {
        foreach (string known in KnownLoaderDisplayNames)
        {
            if (string.Equals(loader, known, StringComparison.OrdinalIgnoreCase))
            {
                return known;
            }
        }

        return loader;
    }

    private static string? ResolveJarVersion(string? version, ZipArchive archive) =>
        version == "${file.jarVersion}" ? ReadManifest(archive).Version ?? version : version;

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

        /// <summary>非 null 時寫入去除色碼後的值</summary>
        internal void SetId(string? raw)
        {
            if (raw is not null)
            {
                Id = ModHelpers.StripColorAndFormattingCodes(raw);
            }
        }

        /// <summary>非 null 時寫入去除色碼後的值</summary>
        internal void SetName(string? raw)
        {
            if (raw is not null)
            {
                Name = ModHelpers.StripColorAndFormattingCodes(raw);
            }
        }

        /// <summary>非 null 時寫入去除色碼後的值</summary>
        internal void SetDescription(string? raw)
        {
            if (raw is not null)
            {
                Description = ModHelpers.StripColorAndFormattingCodes(raw);
            }
        }

        /// <summary>非 null 時寫入去除色碼後的值</summary>
        internal void SetAuthor(string? raw)
        {
            if (raw is not null)
            {
                Author = ModHelpers.StripColorAndFormattingCodes(raw);
            }
        }

        /// <summary>非空白時寫入去除色碼後的版本號</summary>
        internal void SetVersion(string? raw)
        {
            if (!string.IsNullOrWhiteSpace(raw))
            {
                Version = ModHelpers.StripColorAndFormattingCodes(raw);
            }
        }

        internal void SetMinecraftVersionIfValid(string? raw)
        {
            if (!string.IsNullOrWhiteSpace(raw))
            {
                string normalized = MinecraftVersionSemantics.NormalizeMinecraftVersion(raw);
                if (!string.IsNullOrWhiteSpace(normalized))
                {
                    MinecraftVersion = normalized;
                }
            }
        }

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

        internal static LocalModMetadataBuilder FromDictionary(IReadOnlyDictionary<string, string> dict, string fallbackName) => new()
        {
            Id = dict.GetValueOrDefault("id", string.Empty),
            Name = dict.GetValueOrDefault("name", fallbackName),
            Version = NormalizeUnknown(dict.TryGetValue("version", out string? v) ? v : null),
            MinecraftVersion = NormalizeUnknown(dict.TryGetValue("mc_version", out string? mc) ? mc : null),
            LoaderType = NormalizeUnknown(dict.TryGetValue("loader_type", out string? lt) ? lt : null) is { } loader ? NormalizeLoaderDisplayName(loader) : null,
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

        internal LocalModInfo ToModInfo(
            string fileName,
            string baseStem,
            long fileSize,
            double fileMtime,
            bool isEnabled,
            string? cachedHash) =>
            new(
                id: string.IsNullOrWhiteSpace(Id) ? baseStem : Id,
                name: string.IsNullOrWhiteSpace(Name) ? baseStem : Name,
                fileName: fileName,
                version: Version ?? "未知",
                minecraftVersion: MinecraftVersion ?? "未知",
                loaderType: LoaderType ?? "未知",
                description: Description,
                author: Author,
                platform: Platform,
                status: isEnabled ? ModStatus.Enabled : ModStatus.Disabled,
                fileSize: fileSize,
                fileMtime: fileMtime,
                currentHash: cachedHash ?? string.Empty,
                hashAlgorithm: string.IsNullOrEmpty(cachedHash) ? string.Empty : ModHelpers.PreferredHashAlgorithm);
    }
}
