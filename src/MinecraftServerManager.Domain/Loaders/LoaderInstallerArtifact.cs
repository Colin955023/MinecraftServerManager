namespace MinecraftServerManager.Domain.Loaders;

public sealed record LoaderInstallerArtifact(
    string Url,
    string? ExpectedHash = null,
    string? HashAlgorithm = null,
    string Version = "");
