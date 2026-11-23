using System.Text;
using System.Text.Json;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed partial class ServerInspector
{
    /// <summary>偵測結果值與其來源說明（尚未偵測到時來源為「未偵測到」）</summary>
    private sealed class DetectedValue<T>
    {
        public T? Value { get; set; }

        public string Source { get; set; } = "未偵測到";

        /// <summary>等於 T 預設值即視為未偵測到（字串為 null，LoaderKind 為 Unknown）</summary>
        internal bool IsSet => !EqualityComparer<T>.Default.Equals(Value, default);

        public void Set(T value, string source)
        {
            Value = value;
            Source = source;
        }

        internal void SetIfUnset(T value, string source)
        {
            if (!IsSet)
            {
                Set(value, source);
            }
        }
    }

    private static void DetectMinecraftVersionFromMetadata(
        string directory,
        HashSet<string> files,
        ServerLaunchTarget target,
        DetectedValue<string> mcVersion)
    {
        string? rootJsonMc = TryExtractMinecraftVersionFromRootJson(directory);
        if (!string.IsNullOrEmpty(rootJsonMc))
        {
            mcVersion.Set(rootJsonMc, "根目錄 version.json");
            return;
        }

        string? primaryJarPath = files.Contains(ServerDefaults.ServerJarFileName)
            ? Path.Combine(directory, ServerDefaults.ServerJarFileName)
            : !string.IsNullOrEmpty(target.Value) && ModHelpers.IsJarFileName(target.Value)
                ? Path.Combine(directory, target.Value)
                : null;

        if (primaryJarPath is not null && SafeFileSystem.FileExists(primaryJarPath))
        {
            string? jarMc = TryExtractMinecraftVersionFromJar(primaryJarPath);
            if (!string.IsNullOrEmpty(jarMc))
            {
                mcVersion.Set(jarMc, $"{Path.GetFileName(primaryJarPath)} 內部 metadata");
            }
        }
    }

    private static void DetectLoaderFromLibraries(
        string directory,
        DetectedValue<LoaderKind> loaderType,
        DetectedValue<string> loaderVersion,
        DetectedValue<string> mcVersion)
    {
        string librariesDir = Path.Combine(directory, ServerDefaults.LibrariesDirectoryName);
        if (!SafeFileSystem.DirectoryExists(librariesDir))
        {
            return;
        }

        foreach (var kind in DetectableLibraryLoaders)
        {
            var layout = LoaderLayout.For(kind);
            string libDir = layout.GetLibraryDirectory(directory);
            if (!SafeFileSystem.DirectoryExists(libDir))
            {
                continue;
            }

            string relative = layout.LibraryRelativePath;
            loaderType.Set(kind, relative);

            try
            {
                if (kind == LoaderKind.Forge)
                {
                    foreach (string dirName in ListVersionDirectoriesNewestFirst(libDir))
                    {
                        int dash = dirName.IndexOf('-');
                        if (dash > 0)
                        {
                            mcVersion.SetIfUnset(dirName[..dash], $"{relative}/{dirName}");
                            loaderVersion.SetIfUnset(dirName[(dash + 1)..], $"{relative}/{dirName}");
                            break;
                        }
                    }
                }
                else if (FindNewestVersionDirectory(libDir) is { } verName)
                {
                    loaderVersion.Set(verName, $"{relative}/{verName}");
                    if (kind == LoaderKind.NeoForge)
                    {
                        string? derived = MinecraftVersionSemantics.DeriveMinecraftVersionFromNeoForge(verName);
                        if (!string.IsNullOrEmpty(derived))
                        {
                            mcVersion.SetIfUnset(derived, $"從 NeoForge {verName} 推導");
                        }
                    }
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Logger.Warning(ex, "偵測 {Loader} 函式庫目錄失敗", kind);
            }
        }
    }

    private static void DetectLoaderFromMarkers(HashSet<string> files, ServerLaunchTarget target, DetectedValue<LoaderKind> loaderType)
    {
        if (loaderType.IsSet)
        {
            return;
        }

        string fabricLauncher = LoaderLayout.For(LoaderKind.Fabric).LauncherJarFileName;
        string quiltLauncher = LoaderLayout.For(LoaderKind.Quilt).LauncherJarFileName;
        if (LoaderLayout.IsPaperJarName(target.Value) ||
            files.Any(static f => f.StartsWith("paper-", StringComparison.OrdinalIgnoreCase) && ModHelpers.IsJarFileName(f)) ||
            files.Contains("paper-global.yml") || files.Contains("paper.yml") || files.Contains("paper-world-defaults.yml"))
        {
            loaderType.Set(LoaderKind.Paper, "Paper 伺服器特徵 (paper.jar 或 paper-global.yml)");
        }
        else if (files.Contains(fabricLauncher))
        {
            loaderType.Set(LoaderKind.Fabric, $"{fabricLauncher} 啟動檔名");
        }
        else if (files.Contains(quiltLauncher))
        {
            loaderType.Set(LoaderKind.Quilt, $"{quiltLauncher} 啟動檔名");
        }
        else if (target.Value.Equals(ServerDefaults.ServerJarFileName, StringComparison.OrdinalIgnoreCase) ||
                 target.Value.Equals("minecraft_server.jar", StringComparison.OrdinalIgnoreCase))
        {
            loaderType.Set(LoaderKind.Vanilla, "官方標準 server.jar 檔名");
        }
    }

    private static void DetectFromLaunchTargetFileName(
        ServerLaunchTarget target,
        DetectedValue<LoaderKind> loaderType,
        DetectedValue<string> loaderVersion,
        DetectedValue<string> mcVersion)
    {
        string exeName = target.Value;
        var paperMatch = PaperJarRegex().Match(exeName);
        if (paperMatch.Success)
        {
            mcVersion.SetIfUnset(paperMatch.Groups["mcVer"].Value, $"{exeName} 檔名");
            loaderVersion.SetIfUnset(paperMatch.Groups["build"].Value, $"{exeName} 檔名");
            loaderType.Set(LoaderKind.Paper, $"{exeName} 檔名");
        }

        var forgeMatch = ForgeJarRegex().Match(exeName);
        if (forgeMatch.Success)
        {
            mcVersion.SetIfUnset(forgeMatch.Groups[1].Value, $"{exeName} 檔名");
            loaderVersion.SetIfUnset(forgeMatch.Groups[2].Value, $"{exeName} 檔名");
            loaderType.SetIfUnset(LoaderKind.Forge, $"{exeName} 檔名");
        }
        else if (!mcVersion.IsSet)
        {
            string? extractedMc = MinecraftVersionSemantics.ExtractMinecraftVersionFromText(exeName);
            if (!string.IsNullOrEmpty(extractedMc))
            {
                mcVersion.Set(extractedMc, $"{exeName} 檔名");
            }
        }
    }

    private static void DetectFromLaunchScripts(
        string directory,
        DetectedValue<LoaderKind> loaderType,
        DetectedValue<string> loaderVersion,
        DetectedValue<string> mcVersion)
    {
        string runBat = Path.Combine(directory, ServerDefaults.RunBatFileName);
        string winArgs = Path.Combine(directory, ServerDefaults.WinArgsFileName);
        string toCheck = SafeFileSystem.FileExists(runBat) ? runBat : (SafeFileSystem.FileExists(winArgs) ? winArgs : string.Empty);
        if (string.IsNullOrEmpty(toCheck) || SafeFileSystem.GetFileLength(toCheck) > MaxMetadataBytes)
        {
            return;
        }

        try
        {
            string content = SafeFileSystem.ReadAllText(toCheck);
            var m = ForgeJarRegex().Match(content);
            if (m.Success)
            {
                string source = $"{Path.GetFileName(toCheck)} 腳本內容";
                mcVersion.SetIfUnset(m.Groups[1].Value, source);
                loaderVersion.SetIfUnset(m.Groups[2].Value, source);
                loaderType.SetIfUnset(LoaderKind.Forge, source);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "檢查啟動腳本失敗");
        }
    }

    private static void DetectFromLogs(
        string directory,
        DetectedValue<LoaderKind> loaderType,
        DetectedValue<string> loaderVersion,
        DetectedValue<string> mcVersion)
    {
        string? logFile = FindLatestLogFile(directory);
        if (logFile is null || !SafeFileSystem.FileExists(logFile))
        {
            return;
        }

        string fileName = Path.GetFileName(logFile);
        try
        {
            using var sr = new StreamReader(SafeFileSystem.OpenRead(logFile), Encoding.UTF8);
            int lineCount = 0;
            string? line;
            while ((line = sr.ReadLine()) is not null && lineCount++ < 2000)
            {
                if (!mcVersion.IsSet)
                {
                    var mcMatch = McLogRegex().Match(line);
                    if (mcMatch.Success)
                    {
                        mcVersion.Set(mcMatch.Groups[1].Value, $"{fileName} 啟動記錄");
                    }
                }

                if (!loaderVersion.IsSet)
                {
                    var forgeM = ForgeLogRegex().Match(line);
                    if (forgeM.Success)
                    {
                        loaderVersion.Set(forgeM.Groups[1].Value, $"{fileName} 載入器記錄");
                        loaderType.SetIfUnset(LoaderKind.Forge, $"{fileName} 載入器記錄");
                    }
                    else
                    {
                        var neoM = NeoForgeLogRegex().Match(line);
                        if (neoM.Success)
                        {
                            loaderVersion.Set(neoM.Groups[1].Value, $"{fileName} 載入器記錄");
                            loaderType.SetIfUnset(LoaderKind.NeoForge, $"{fileName} 載入器記錄");
                        }
                    }
                }

                if (mcVersion.IsSet && loaderVersion.IsSet)
                {
                    break;
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "讀取伺服器記錄檔失敗");
        }
    }

    /// <summary>列出函式庫下的版本資料夾名稱，依版本降冪（多版本並存時優先採用最新者）</summary>
    private static IEnumerable<string> ListVersionDirectoriesNewestFirst(string libraryDirectory) =>
        SafeFileSystem.ListBoundedDirectory(libraryDirectory, maxEntries: 64, maxTotalBytes: SafeFileSystem.DefaultMaxTotalBytes, rejectReparse: false)
            .Where(static e => e.IsDirectory)
            .Select(static e => Path.GetFileName(e.FullPath))
            .OrderDescending(VersionNameComparer.Instance);

    private static string? FindNewestVersionDirectory(string libraryDirectory) =>
        ListVersionDirectoriesNewestFirst(libraryDirectory).FirstOrDefault();

    private const long MaxMetadataBytes = 2L * 1024 * 1024;

    private static string? TryExtractMinecraftVersionFromRootJson(string directory)
    {
        string jsonPath = Path.Combine(directory, "version.json");
        if (!SafeFileSystem.FileExists(jsonPath))
        {
            return null;
        }

        try
        {
            byte[]? payload = SafeFileSystem.ReadRegularFile(jsonPath, MaxMetadataBytes);
            if (payload is null)
            {
                return null;
            }

            return ExtractMinecraftVersionFromVersionJson(payload);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            Logger.Warning(ex, "解析 version.json 失敗");
        }
        return null;
    }

    private static string? ExtractMinecraftVersionFromVersionJson(byte[] payload)
    {
        using var doc = JsonCodec.ParseDocument(payload);
        var root = doc.RootElement;
        foreach (string prop in VersionJsonCandidateProperties)
        {
            if (root.GetStringOrNull(prop) is { Length: > 0 } text
                && MinecraftVersionSemantics.ExtractMinecraftVersionFromText(text) is { Length: > 0 } extracted)
            {
                return extracted;
            }
        }

        return null;
    }

    private static string? TryExtractMinecraftVersionFromJar(string jarPath)
    {
        try
        {
            using var zip = SafeZipArchive.OpenRead(jarPath);
            var versionEntry = zip.GetEntry("version.json");
            if (versionEntry is not null && SafeZipArchive.ReadEntryBytesBounded(versionEntry, (int)MaxMetadataBytes) is { } versionBytes)
            {
                if (ExtractMinecraftVersionFromVersionJson(versionBytes) is { } fromJson)
                {
                    return fromJson;
                }
            }

            var manifestEntry = zip.GetEntry("META-INF/MANIFEST.MF");
            if (manifestEntry is not null && SafeZipArchive.ReadEntryTextBounded(manifestEntry, (int)MaxMetadataBytes) is { } manifestText)
            {
                return ExtractMinecraftVersionFromManifest(manifestText);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException or JsonException)
        {
            Logger.Warning(ex, "解析 JAR 清單版本失敗");
        }
        return null;
    }

    /// <summary>僅取 MANIFEST.MF 的 Implementation-Version／Specification-Version，避免 Manifest-Version: 1.0 被誤判為 MC 1.0</summary>
    internal static string? ExtractMinecraftVersionFromManifest(string manifestText)
    {
        foreach (var range in manifestText.AsSpan().EnumerateLines())
        {
            ReadOnlySpan<char> line = range;
            foreach (string key in ManifestVersionKeys)
            {
                if (line.StartsWith(key, StringComparison.OrdinalIgnoreCase)
                    && line.Length > key.Length
                    && line[key.Length] == ':'
                    && MinecraftVersionSemantics.ExtractMinecraftVersionFromText(line[(key.Length + 1)..].Trim().ToString()) is { Length: > 0 } extracted)
                {
                    return extracted;
                }
            }
        }

        return null;
    }
}
