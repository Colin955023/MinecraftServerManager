using System.Collections.Frozen;
using MinecraftServerManager.Core.Errors;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.Infrastructure.Java;

/// <summary>
/// 透過 Windows winget 套件管理員自動安裝 Java
/// </summary>
public sealed class JavaWingetInstaller(IProcessRunner processRunner) : IJavaInstaller
{
    private static readonly FrozenDictionary<uint, string> WingetErrorMessages = new Dictionary<uint, string>
    {
        [1602] = "使用者取消安裝",
        [1603] = "安裝過程發生嚴重錯誤",
        [1618] = "另一個安裝程式正在執行中，請稍後重試",
        [0x800704C7] = "使用者取消安裝或拒絕 UAC 驗證",
        [0x80070005] = "存取被拒，需要系統管理員權限",
        [0x8A150008] = "下載套件失敗",
        [0x8A15000F] = "下載套件逾時或網路連線中斷",
        [0x8A150011] = "未在來源找到指定的 Java 套件",
        [0x8A150014] = "套件雜湊值不相符，檔案可能損毀",
        [0x8A15002B] = "授權條款未接受",
        [0x8A15002C] = "系統環境或架構不支援此套件",
        [0x8A150044] = "安裝程式執行失敗",
        [0x8A150056] = "系統已安裝此版本套件",
    }.ToFrozenDictionary();

    public async Task<bool> IsWingetAvailableAsync(CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(processRunner);

        try
        {
            var process = await processRunner.StartAsync(
                new ProcessStartSpec("winget", ["--version"]),
                cancellationToken).ConfigureAwait(false);
            await using (process.ConfigureAwait(false))
            {
                var result = await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
                return result.ExitCode == 0;
            }
        }
        catch
        {
            return false;
        }
    }

    public async Task<ProcessExitResult> InstallWithWingetAsync(
        int majorVersion,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(processRunner);

        if (!await IsWingetAvailableAsync(cancellationToken).ConfigureAwait(false))
        {
            throw new JavaInstallException("無法呼叫 winget 工具，請確認系統已安裝「應用程式安裝員 (App Installer)」");
        }

        string packageId = ResolvePackageId(majorVersion);

        try
        {
            var process = await processRunner.StartAsync(
                new ProcessStartSpec(
                    "winget",
                    ["install", "--accept-package-agreements", "--accept-source-agreements", packageId]),
                cancellationToken).ConfigureAwait(false);
            await using (process.ConfigureAwait(false))
            {
                var result = await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
                if (result.ExitCode != 0)
                {
                    uint unsignedCode = unchecked((uint)result.ExitCode);
                    string hexCode = $"0x{unsignedCode:X8}";

                    string reason = WingetErrorMessages.TryGetValue(unsignedCode, out string? message)
                        ? message
                        : $"結束代碼: {hexCode}";

                    throw new JavaInstallException(
                        $"透過 winget 安裝 {packageId} 失敗：{reason} ({hexCode})",
                        result.ExitCode);
                }

                return result;
            }
        }
        catch (JavaInstallException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new JavaInstallException($"透過 winget 安裝 {packageId} 發生例外：{ex.Message}", ex);
        }
    }

    public static string ResolvePackageId(int majorVersion) => majorVersion switch
    {
        8 => "Oracle.JavaRuntimeEnvironment",
        11 or 16 or 17 or 21 or 25 => $"Microsoft.OpenJDK.{majorVersion}",
        _ => throw new JavaInstallException($"不支援自動安裝 Java 主要版本 {majorVersion}，請手動前往官網下載")
    };
}
