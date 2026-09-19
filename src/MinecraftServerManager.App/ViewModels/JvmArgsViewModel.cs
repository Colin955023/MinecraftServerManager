using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Utilities;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 單一建議 JVM 參數項目模型
/// </summary>
public sealed partial class JvmArgOptionItem(string option, string description, bool isChecked = true) : ObservableObject
{
    public string Option { get; } = option;

    public string Description { get; } = description;

    [ObservableProperty]
    private bool _isChecked = isChecked;
}

/// <summary>
/// JVM 參數設定對話框 ViewModel
/// </summary>
public sealed partial class JvmArgsViewModel : ObservableObject
{
    private readonly int? _javaMajor;
    private readonly int _memoryMaxMb;
    private readonly string _loaderType;
    private readonly HashSet<string> _recommendedSet = new(StringComparer.OrdinalIgnoreCase);

    [ObservableProperty]
    private string _descriptionText = string.Empty;

    [ObservableProperty]
    private bool _hasCustomArgs;

    [ObservableProperty]
    private string _customArgsText = string.Empty;

    public ObservableCollection<JvmArgOptionItem> RecommendedArgs { get; } = [];

    public JvmArgsViewModel(
        int? javaMajor,
        int memoryMaxMb,
        string loaderType = "",
        IEnumerable<string>? existingArgs = null)
    {
        _javaMajor = javaMajor;
        _memoryMaxMb = memoryMaxMb;
        _loaderType = loaderType;

        InitDescriptionText();
        LoadArgs(existingArgs);
    }

    private void InitDescriptionText()
    {
        if (_javaMajor.HasValue && _javaMajor.Value >= 21)
        {
            DescriptionText = $"目前偵測為 Java {_javaMajor.Value}，已自動套用 ZGC 低延遲最佳化設定。滑鼠游標移至項目可查看說明。";
        }
        else if (_javaMajor.HasValue)
        {
            DescriptionText = $"目前偵測為 Java {_javaMajor.Value}，已自動套用 G1GC (Aikar's Flags) 最佳化設定。滑鼠游標移至項目可查看說明。";
        }
        else
        {
            DescriptionText = "Java 21+ 建議使用 ZGC；Java 8/16/17 建議使用 G1GC。滑鼠游標移至項目可查看說明。";
        }
    }

    private void LoadArgs(IEnumerable<string>? existingArgs)
    {
        var details = JvmOptionPolicy.GetRecommendedJvmArgsDetails(_javaMajor, _memoryMaxMb, _loaderType);
        foreach (var (opt, _) in details)
        {
            _recommendedSet.Add(opt);
        }

        var existingList = existingArgs?.ToList() ?? [];
        bool isFirstTime = existingArgs is null;

        RecommendedArgs.Clear();
        foreach (var (opt, desc) in details)
        {
            bool isChecked = isFirstTime || existingList.Contains(opt, StringComparer.OrdinalIgnoreCase);
            RecommendedArgs.Add(new JvmArgOptionItem(opt, desc, isChecked));
        }

        var customList = existingList.Where(arg => !_recommendedSet.Contains(arg)).ToList();
        if (customList.Count > 0)
        {
            HasCustomArgs = true;
            CustomArgsText = string.Join(" ", customList);
        }
        else
        {
            HasCustomArgs = false;
            CustomArgsText = string.Empty;
        }
    }

    [RelayCommand]
    public void ResetToDefault()
    {
        foreach (var item in RecommendedArgs)
        {
            item.IsChecked = true;
        }
        HasCustomArgs = false;
        CustomArgsText = string.Empty;
    }

    /// <summary>
    /// 取得使用者勾選與自訂的最終 JVM 參數清單
    /// </summary>
    public IReadOnlyList<string> GetFinalJvmArgs()
    {
        var result = new List<string>();
        foreach (var item in RecommendedArgs)
        {
            if (item.IsChecked)
            {
                result.Add(item.Option);
            }
        }

        if (HasCustomArgs && !string.IsNullOrWhiteSpace(CustomArgsText))
        {
            var customTokens = JvmOptionPolicy.NormalizeJvmArgs(CustomArgsText);
            foreach (string token in customTokens)
            {
                if (!result.Contains(token, StringComparer.OrdinalIgnoreCase))
                {
                    result.Add(token);
                }
            }
        }

        return result;
    }
}
