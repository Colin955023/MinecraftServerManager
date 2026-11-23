namespace MinecraftServerManager.UnitTests.Architecture;

/// <summary>組合根安全設定回歸測試（共用 HttpClient 處理常式需由真實組合根建立，故以原始碼驗證）</summary>
public sealed class CompositionRootConfigurationTests
{
    [Fact]
    public void SharedHttpHandler_CompositionRootSource_DisablesProxyAndUsesUrlPolicyCallback()
    {
        string path = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.App", "AppCompositionRoot.cs");
        string code = SourceScanner.StripCommentsOnly(File.ReadAllText(path));

        // ConnectCallback 逐一檢查解析後位址；經代理時檢查的會是代理而非目標，故必須停用系統代理
        Assert.Matches(@"\bUseProxy\s*=\s*false\b", code);
        Assert.Matches(@"\bAllowAutoRedirect\s*=\s*false\b", code);
        Assert.Matches(@"\bConnectCallback\s*=\s*HttpUrlPolicy\.ConnectAsync\b", code);
    }
}
