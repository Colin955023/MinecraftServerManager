using System.Buffers;
using System.Collections.Concurrent;
using System.IO.Compression;
using System.Text;
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
    private const int MaxMetadataEntryBytes = 256 * 1024;

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

        if (!SafeFileSystem.FileExists(filePath))
        {
            return Task.FromResult<LocalModInfo?>(null);
        }

        FileSystemMetadata fileInfo = SafeFileSystem.GetFileMetadata(filePath);
        string fileName = fileInfo.Name;
        bool isEnabled = !fileName.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase);
        string baseStem = ModHelpers.ModFilenameStem(fileName);

        // 讀取快取（若為 ModIndexPersistence 則一併檢查檔案大小與最後修改時間）
        IReadOnlyDictionary<string, string>? cached = null;
        if (persistence is ModIndexPersistence concretePersistence)
        {
            var cachedEntry = concretePersistence.GetEntry(fileName);
            if (cachedEntry is not null &&
                cachedEntry.FileSizeBytes == fileInfo.Length &&
                cachedEntry.LastWriteTimeUtcTicks == fileInfo.LastWriteTimeUtc.Ticks)
            {
                cached = cachedEntry.Metadata;
            }
        }
        else
        {
            cached = persistence?.GetCachedMetadata(fileName);
        }

        LocalModMetadataBuilder metadata;

        if (cached is not null && cached.TryGetValue("name", out string? cachedName) && !string.IsNullOrWhiteSpace(cachedName))
        {
            metadata = LocalModMetadataBuilder.FromDictionary(cached, baseStem);
        }
        else
        {
            metadata = ExtractMetadataFromJar(filePath, baseStem);
            ApplyFallbackLogic(baseStem, metadata);
            if (persistence is ModIndexPersistence concreteWriter)
            {
                concreteWriter.CacheMetadata(fileName, metadata.ToDictionary(), fileInfo.Length, fileInfo.LastWriteTimeUtc.Ticks);
            }
            else
            {
                persistence?.CacheMetadata(fileName, metadata.ToDictionary());
            }
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

    private static string? ReadEntryTextBounded(ZipArchiveEntry entry, int maxBytes = MaxMetadataEntryBytes)
    {
        if (entry.Length > maxBytes)
        {
            return null;
        }

        int rentSize = (int)Math.Min(entry.Length > 0 ? entry.Length + 1 : 4096, maxBytes + 1);
        using var stream = entry.Open();
        byte[] buffer = ArrayPool<byte>.Shared.Rent(rentSize);
        try
        {
            int totalRead = 0;
            while (totalRead < rentSize)
            {
                int read = stream.Read(buffer, totalRead, rentSize - totalRead);
                if (read == 0)
                {
                    break;
                }
                totalRead += read;
            }

            // 若 entry.Length 未知且資料超出初始租用大小，回退至完整讀取
            if (totalRead == rentSize && rentSize < maxBytes + 1)
            {
                int nextByte = stream.ReadByte();
                if (nextByte != -1)
                {
                    byte[] largeBuffer = ArrayPool<byte>.Shared.Rent(maxBytes + 1);
                    try
                    {
                        Buffer.BlockCopy(buffer, 0, largeBuffer, 0, totalRead);
                        largeBuffer[totalRead++] = (byte)nextByte;
                        while (totalRead <= maxBytes)
                        {
                            int read = stream.Read(largeBuffer, totalRead, maxBytes + 1 - totalRead);
                            if (read == 0)
                            {
                                break;
                            }
                            totalRead += read;
                        }

                        if (totalRead > maxBytes)
                        {
                            return null;
                        }

                        ReadOnlySpan<byte> largeSpan = largeBuffer.AsSpan(0, totalRead);
                        if (largeSpan.StartsWith(Encoding.UTF8.Preamble))
                        {
                            largeSpan = largeSpan[Encoding.UTF8.Preamble.Length..];
                        }

                        return Encoding.UTF8.GetString(largeSpan);
                    }
                    finally
                    {
                        ArrayPool<byte>.Shared.Return(largeBuffer);
                    }
                }
            }

            if (totalRead > maxBytes)
            {
                return null;
            }

            ReadOnlySpan<byte> span = buffer.AsSpan(0, totalRead);
            if (span.StartsWith(Encoding.UTF8.Preamble))
            {
                span = span[Encoding.UTF8.Preamble.Length..];
            }

            return Encoding.UTF8.GetString(span);
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private static LocalModMetadataBuilder ExtractMetadataFromJar(string filePath, string fallbackName)
    {
        var meta = new LocalModMetadataBuilder { Name = fallbackName };

        try
        {
            using var archive = SafeZipArchive.OpenRead(filePath);

            // 1. fabric.mod.json / quilt.mod.json
            var fabricEntry = archive.GetEntry("fabric.mod.json") ?? archive.GetEntry("quilt.mod.json");
            if (fabricEntry is not null && ReadEntryTextBounded(fabricEntry) is { } fabricJson)
            {
                using var doc = JsonCodec.ParseDocument(fabricJson);
                ParseFabricJson(doc.RootElement, meta, archive);
                return meta;
            }

            // 2. META-INF/mods.toml / META-INF/neoforge.mods.toml (Forge / NeoForge)
            var forgeEntry = archive.GetEntry("META-INF/mods.toml") ?? archive.GetEntry("META-INF/neoforge.mods.toml");
            if (forgeEntry is not null && ReadEntryTextBounded(forgeEntry) is { } content)
            {
                ParseForgeToml(content, meta, archive);
                return meta;
            }

            // 3. mcmod.info (Legacy Forge)
            var legacyEntry = archive.GetEntry("mcmod.info");
            if (legacyEntry is not null && ReadEntryTextBounded(legacyEntry) is { } legacyJson)
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
        catch
        {
        }

        return meta;
    }

    private static bool TryExtractFromManifestOrJarJar(ZipArchive archive, LocalModMetadataBuilder meta)
    {
        string? embeddedPath = null;
        string? manifestTitle = null;
        string? manifestVendor = null;
        string? manifestVersion = null;

        var mfEntry = archive.GetEntry("META-INF/MANIFEST.MF");
        if (mfEntry is not null && mfEntry.Length <= MaxMetadataEntryBytes)
        {
            try
            {
                using var stream = mfEntry.Open();
                using var reader = new StreamReader(stream, Encoding.UTF8);
                string? line;
                while ((line = reader.ReadLine()) is not null)
                {
                    int colon = line.IndexOf(':');
                    if (colon <= 0)
                    {
                        continue;
                    }

                    string key = line[..colon].Trim();
                    string val = line[(colon + 1)..].Trim();

                    if (key.Equals("Embedded-Dependencies-Mod", StringComparison.OrdinalIgnoreCase))
                    {
                        embeddedPath = val;
                    }
                    else if (key.Equals("Specification-Title", StringComparison.OrdinalIgnoreCase) ||
                             key.Equals("Implementation-Title", StringComparison.OrdinalIgnoreCase))
                    {
                        manifestTitle ??= val;
                    }
                    else if (key.Equals("Specification-Vendor", StringComparison.OrdinalIgnoreCase) ||
                             key.Equals("Implementation-Vendor", StringComparison.OrdinalIgnoreCase))
                    {
                        manifestVendor ??= val;
                    }
                    else if (key.Equals("Implementation-Version", StringComparison.OrdinalIgnoreCase))
                    {
                        manifestVersion ??= val;
                    }
                }
            }
            catch
            {
            }
        }

        // 優先從指定或搜尋到的內嵌 JAR 讀取 mods.toml / fabric.mod.json
        ZipArchiveEntry? innerJarEntry = null;
        if (!string.IsNullOrWhiteSpace(embeddedPath))
        {
            innerJarEntry = archive.GetEntry(embeddedPath.Replace('\\', '/'));
        }

        innerJarEntry ??= archive.Entries.FirstOrDefault(static e =>
            (e.FullName.StartsWith("META-INF/jarjar/", StringComparison.OrdinalIgnoreCase) ||
             e.FullName.StartsWith("META-INF/jars/", StringComparison.OrdinalIgnoreCase)) &&
            e.FullName.EndsWith(".jar", StringComparison.OrdinalIgnoreCase) &&
            e.Length <= 10 * 1024 * 1024);

        if (innerJarEntry is { Length: <= 10 * 1024 * 1024 })
        {
            try
            {
                using var innerStream = innerJarEntry.Open();
                int initialCapacity = innerJarEntry.Length > 0 ? (int)Math.Min(innerJarEntry.Length, 10 * 1024 * 1024) : 0;
                using var ms = new MemoryStream(initialCapacity);
                innerStream.CopyTo(ms);
                ms.Position = 0;
                using var innerZip = SafeZipArchive.OpenRead(ms, leaveOpen: true, maxArchiveBytes: 10 * 1024 * 1024);

                var innerToml = innerZip.GetEntry("META-INF/mods.toml") ?? innerZip.GetEntry("META-INF/neoforge.mods.toml");
                if (innerToml is not null && innerToml.Length <= MaxMetadataEntryBytes)
                {
                    using var s = innerToml.Open();
                    using var r = new StreamReader(s);
                    string tomlContent = r.ReadToEnd();
                    ParseForgeToml(tomlContent, meta, innerZip);
                    if ((meta.Version == "未知" || string.IsNullOrWhiteSpace(meta.Version)) && !string.IsNullOrWhiteSpace(manifestVersion))
                    {
                        meta.Version = ModHelpers.StripColorAndFormattingCodes(manifestVersion);
                    }
                    return true;
                }

                var innerFabric = innerZip.GetEntry("fabric.mod.json") ?? innerZip.GetEntry("quilt.mod.json");
                if (innerFabric is not null && innerFabric.Length <= MaxMetadataEntryBytes)
                {
                    using var s = innerFabric.Open();
                    using var doc = JsonCodec.ParseDocument(s);
                    ParseFabricJson(doc.RootElement, meta, innerZip);
                    if ((meta.Version == "未知" || string.IsNullOrWhiteSpace(meta.Version)) && !string.IsNullOrWhiteSpace(manifestVersion))
                    {
                        meta.Version = ModHelpers.StripColorAndFormattingCodes(manifestVersion);
                    }
                    return true;
                }
            }
            catch
            {
            }
        }

        if (!string.IsNullOrWhiteSpace(manifestTitle))
        {
            meta.Name = ModHelpers.StripColorAndFormattingCodes(manifestTitle);
            if (!string.IsNullOrWhiteSpace(manifestVendor))
            {
                meta.Author = ModHelpers.StripColorAndFormattingCodes(manifestVendor);
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
            string v = verElem.GetString() ?? meta.Version;
            if (v == "${file.jarVersion}")
            {
                v = ReadManifestVersion(archive) ?? v;
            }
            meta.Version = ModHelpers.StripColorAndFormattingCodes(v);
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
                string? parsedValue = ExtractTomlValueAt(modSection, eqIdx + 1, ref nextIdx);
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
                v = ReadManifestVersion(archive) ?? v;
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

        string? mcDepRange = ExtractForgeMinecraftDependency(content);
        if (!string.IsNullOrWhiteSpace(mcDepRange))
        {
            string normalized = MinecraftVersionSemantics.NormalizeMinecraftVersion(mcDepRange);
            if (!string.IsNullOrWhiteSpace(normalized))
            {
                meta.MinecraftVersion = normalized;
            }
        }
    }

    private static string? ExtractForgeMinecraftDependency(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
        {
            return null;
        }

        int idx = 0;
        while ((idx = content.IndexOf("[[dependencies", idx, StringComparison.OrdinalIgnoreCase)) >= 0)
        {
            int nextSection = content.IndexOf("[[", idx + 14, StringComparison.Ordinal);
            string section = nextSection >= 0 ? content[idx..nextSection] : content[idx..];
            if (ForgeMinecraftModIdRegex().IsMatch(section))
            {
                var match = ForgeVersionRangeRegex().Match(section);
                if (match.Success)
                {
                    return CleanTomlValue(match.Groups[1].Value);
                }
            }
            if (nextSection < 0)
            {
                break;
            }
            idx = nextSection;
        }

        var directMatch = ForgeMcDepRegex().Match(content);
        if (directMatch.Success)
        {
            return CleanTomlValue(directMatch.Groups[1].Value);
        }

        return null;
    }

    private static string? ExtractTomlValueAt(string content, int pos, ref int nextIndex)
    {
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
            if (end >= 0)
            {
                nextIndex = Math.Max(nextIndex, end + 3);
                return content[(pos + 3)..end].Trim();
            }
            nextIndex = content.Length;
            return content[(pos + 3)..].Trim();
        }

        if (pos + 3 <= content.Length && content.AsSpan(pos, 3).SequenceEqual("\"\"\""))
        {
            int end = content.IndexOf("\"\"\"", pos + 3, StringComparison.Ordinal);
            if (end >= 0)
            {
                nextIndex = Math.Max(nextIndex, end + 3);
                return content[(pos + 3)..end].Trim();
            }
            nextIndex = content.Length;
            return content[(pos + 3)..].Trim();
        }

        if (content[pos] == '\'')
        {
            int end = content.IndexOf('\'', pos + 1);
            if (end >= 0)
            {
                nextIndex = Math.Max(nextIndex, end + 1);
                return content[(pos + 1)..end].Trim();
            }
            return content[(pos + 1)..].Trim();
        }

        if (content[pos] == '"')
        {
            int end = -1;
            for (int i = pos + 1; i < content.Length; i++)
            {
                if (content[i] == '"')
                {
                    int backslashes = 0;
                    for (int j = i - 1; j > pos && content[j] == '\\'; j--)
                    {
                        backslashes++;
                    }
                    if (backslashes % 2 == 0)
                    {
                        end = i;
                        break;
                    }
                }
            }
            if (end >= 0)
            {
                nextIndex = Math.Max(nextIndex, end + 1);
                return UnescapeTomlString(content[(pos + 1)..end].Trim());
            }
            return UnescapeTomlString(content[(pos + 1)..].Trim());
        }

        int eol = content.IndexOf('\n', pos);
        string rawVal = eol >= 0 ? content[pos..eol] : content[pos..];
        if (eol >= 0)
        {
            nextIndex = Math.Max(nextIndex, eol + 1);
        }
        else
        {
            nextIndex = content.Length;
        }

        int hashIdx = rawVal.IndexOf('#');
        if (hashIdx >= 0)
        {
            rawVal = rawVal[..hashIdx];
        }

        return rawVal.Trim();
    }

    private static string UnescapeTomlString(string value)
    {
        if (string.IsNullOrEmpty(value) || !value.Contains('\\'))
        {
            return value;
        }

        return value
            .Replace("\\n", "\n", StringComparison.Ordinal)
            .Replace("\\r", "\r", StringComparison.Ordinal)
            .Replace("\\t", "\t", StringComparison.Ordinal)
            .Replace("\\\"", "\"", StringComparison.Ordinal)
            .Replace("\\\\", "\\", StringComparison.Ordinal);
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
            meta.Name = ModHelpers.StripColorAndFormattingCodes(nameElem.GetString() ?? meta.Name);
        }

        if (target.TryGetProperty("version", out var verElem))
        {
            meta.Version = ModHelpers.StripColorAndFormattingCodes(verElem.GetString() ?? meta.Version);
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

    [GeneratedRegex(@"modId\s*=\s*[""']minecraft[""']", RegexOptions.IgnoreCase)]
    private static partial Regex ForgeMinecraftModIdRegex();

    [GeneratedRegex(@"versionRange\s*=\s*(.+)$", RegexOptions.Multiline | RegexOptions.IgnoreCase)]
    private static partial Regex ForgeVersionRangeRegex();
}
