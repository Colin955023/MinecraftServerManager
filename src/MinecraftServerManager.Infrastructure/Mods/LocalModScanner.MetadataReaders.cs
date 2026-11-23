using System.IO.Compression;
using System.Text.Json;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

public sealed partial class LocalModScanner
{
    private static void ParseFabricJson(JsonElement root, LocalModMetadataBuilder meta, ZipArchive archive)
    {
        meta.LoaderType = LoaderFabric;
        meta.SetId(root.GetStringOrNull("id"));

        meta.SetName(root.GetStringOrNull("name"));

        meta.SetVersion(ResolveJarVersion(root.GetStringOrNull("version"), archive));

        meta.SetDescription(root.GetStringOrNull("description"));

        if (root.TryGetProperty("authors", JsonValueKind.Array, out var authorsElem))
        {
            var authors = authorsElem.EnumerateArray()
                .Select(static a => a.GetStringValue() ?? a.GetStringOrNull("name"))
                .Where(static a => !string.IsNullOrWhiteSpace(a))
                .Select(ModHelpers.StripColorAndFormattingCodes);
            meta.Author = string.Join(", ", authors);
        }
        else if (root.GetStringOrNull("authors") is { } author)
        {
            meta.Author = ModHelpers.StripColorAndFormattingCodes(author);
        }

        if (root.TryGetProperty("depends", JsonValueKind.Object, out var dependsElem)
            && dependsElem.TryGetProperty("minecraft", out var mcElem))
        {
            meta.SetMinecraftVersionIfValid(FirstNonEmptyString(mcElem));
        }
    }

    /// <summary>解析 quilt.mod.json（欄位位於 <c>quilt_loader</c> 物件內）</summary>
    private static void ParseQuiltJson(JsonElement root, LocalModMetadataBuilder meta, ZipArchive archive)
    {
        meta.LoaderType = LoaderQuilt;
        if (!root.TryGetProperty("quilt_loader", JsonValueKind.Object, out var loader))
        {
            return;
        }

        meta.SetId(loader.GetStringOrNull("id"));

        meta.SetVersion(ResolveJarVersion(loader.GetStringOrNull("version"), archive));

        if (loader.TryGetProperty("metadata", JsonValueKind.Object, out var metadata))
        {
            meta.SetName(metadata.GetStringOrNull("name"));

            meta.SetDescription(metadata.GetStringOrNull("description"));

            // contributors 為「名稱: 角色」物件
            if (metadata.TryGetProperty("contributors", JsonValueKind.Object, out var contributors))
            {
                meta.Author = string.Join(", ", contributors.EnumerateObject()
                    .Select(static p => ModHelpers.StripColorAndFormattingCodes(p.Name))
                    .Where(static n => !string.IsNullOrWhiteSpace(n)));
            }
        }

        if (loader.TryGetProperty("depends", JsonValueKind.Array, out var depends))
        {
            foreach (var dependency in depends.EnumerateArray())
            {
                if (dependency.ValueKind == JsonValueKind.Object
                    && string.Equals(dependency.GetStringOrNull("id"), "minecraft", StringComparison.OrdinalIgnoreCase)
                    && dependency.TryGetProperty("versions", out var versions))
                {
                    meta.SetMinecraftVersionIfValid(FirstNonEmptyString(versions));
                    break;
                }
            }
        }
    }

    /// <summary>字串值或字串陣列中第一個非空白者</summary>
    private static string? FirstNonEmptyString(JsonElement element)
    {
        if (element.GetStringValue() is { } value)
        {
            return value;
        }

        if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in element.EnumerateArray())
            {
                if (item.GetStringValue() is { } text && !string.IsNullOrWhiteSpace(text))
                {
                    return text;
                }
            }
        }

        return null;
    }

    private static void ParseForgeToml(string content, LocalModMetadataBuilder meta, ZipArchive archive, string loaderType)
    {
        meta.LoaderType = loaderType;

        content = ForgeTomlReader.StripCommentLines(content);
        int depIdx = ForgeTomlReader.FindTableHeader(content, ForgeTomlReader.DependenciesHeader, 0);
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

        meta.SetId(id);
        meta.SetName(name);
        meta.SetVersion(v is not null ? ResolveJarVersion(v, archive) : null);
        meta.SetDescription(desc);
        meta.SetAuthor(author);
        meta.SetMinecraftVersionIfValid(ForgeTomlReader.ExtractMinecraftDependency(content));
    }

    private static void ParseLegacyMcModInfo(JsonElement root, LocalModMetadataBuilder meta)
    {
        meta.LoaderType = LoaderForge;

        // v1 為陣列；v2 為 {"modListVersion":2,"modList":[...]}
        JsonElement list = root.TryGetProperty("modList", JsonValueKind.Array, out var modList) ? modList : root;
        JsonElement target = list.ValueKind == JsonValueKind.Array
            ? list.EnumerateArray().FirstOrDefault(static e => e.ValueKind == JsonValueKind.Object)
            : list;
        if (target.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        if (target.GetStringOrNull("modid") is { Length: > 0 } modId)
        {
            meta.Id = ModHelpers.StripColorAndFormattingCodes(modId);
        }

        meta.SetName(target.GetStringOrNull("name"));

        meta.SetVersion(target.GetStringOrNull("version"));

        meta.SetMinecraftVersionIfValid(target.GetStringOrNull("mcversion"));

        meta.SetDescription(target.GetStringOrNull("description"));

        if (target.TryGetProperty("authorList", JsonValueKind.Array, out var authorListElem)
            || target.TryGetProperty("authors", JsonValueKind.Array, out authorListElem))
        {
            var authors = authorListElem.EnumerateArray()
                .Select(static a => a.GetStringValue())
                .Where(static a => !string.IsNullOrWhiteSpace(a))
                .Select(ModHelpers.StripColorAndFormattingCodes);
            meta.Author = string.Join(", ", authors);
        }
    }

    private readonly record struct ManifestInfo(string? EmbeddedPath, string? Title, string? Vendor, string? Version);

    /// <summary>讀取 MANIFEST.MF 的模組中繼資料</summary>
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
                foreach (string line in UnfoldManifestLines(text))
                {
                    int colon = line.IndexOf(':');
                    if (colon <= 0)
                    {
                        continue;
                    }

                    ReadOnlySpan<char> key = line.AsSpan(0, colon).Trim();
                    ReadOnlySpan<char> val = line.AsSpan(colon + 1).Trim();

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
            Logger.Warning(ex, "讀取模組 MANIFEST.MF 失敗");
        }

        return new ManifestInfo(embeddedPath, title, vendor, version);
    }

    /// <summary>合併 MANIFEST.MF 續行（以單一空白開頭的行接續上一行）</summary>
    private static List<string> UnfoldManifestLines(string text)
    {
        var lines = new List<string>();
        foreach (ReadOnlySpan<char> line in text.AsSpan().EnumerateLines())
        {
            if (line.StartsWith(' ') && lines.Count > 0)
            {
                lines[^1] += line[1..].ToString();
            }
            else if (!line.IsEmpty)
            {
                lines.Add(line.ToString());
            }
        }

        return lines;
    }

    private static string? DetectLoaderDisplayNameFromText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        // NeoForge 須先於 Forge 判斷（名稱包含 forge）
        foreach (string loader in KnownLoaderDisplayNames)
        {
            if (text.Contains(loader, StringComparison.OrdinalIgnoreCase))
            {
                return loader;
            }
        }

        return null;
    }
}
