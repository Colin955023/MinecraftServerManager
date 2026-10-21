using System.Media;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 提供標準 Windows 系統音效回饋輔助工具
/// </summary>
internal static class AudioFeedback
{
    /// <summary>
    /// 播放警告音效
    /// </summary>
    public static void PlayWarning() => SystemSounds.Exclamation.Play();

    /// <summary>
    /// 播放錯誤音效
    /// </summary>
    public static void PlayError() => SystemSounds.Hand.Play();

    /// <summary>
    /// 播放確認詢問音效
    /// </summary>
    public static void PlayQuestion() => SystemSounds.Question.Play();

    /// <summary>
    /// 播放提示資訊音效
    /// </summary>
    public static void PlayInfo() => SystemSounds.Asterisk.Play();
}
