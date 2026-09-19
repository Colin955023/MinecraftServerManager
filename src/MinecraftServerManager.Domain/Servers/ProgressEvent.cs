namespace MinecraftServerManager.Domain.Servers;

public sealed record ProgressEvent(
    string Phase,
    string Message,
    int CompletedUnits = 0,
    int? TotalUnits = null,
    double? OverallPercent = null)
{
    public double? PhasePercent => TotalUnits is > 0
        ? Math.Clamp((double)CompletedUnits / TotalUnits.Value * 100, 0, 100)
        : null;
}
