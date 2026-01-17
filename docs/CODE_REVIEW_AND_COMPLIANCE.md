# MinecraftServerManager 程式碼審查與掃描摘要

本文件只保留「使用的工具」與「最新掃描數據」。

## 最新掃描資訊（2026-01-01）

- **掃描範圍**：`src/`
- **Python 檔案數量**：35
- **程式碼行數（raw lines）**：14962

### 工具與結果

- **編譯檢查**：`python -m compileall -q src`（成功）
- **Vulture（dead code）**：`uv tool run --isolated vulture src --min-confidence 80`
   - 結果：0 筆（exit code 0）
- **Pylint（duplicate-code）**：`uv tool run --isolated pylint src --disable=all --enable=duplicate-code --reports=n --score=n`
   - 結果：0 筆（exit code 0）
- **Bandit（security）**：`uv tool run --isolated bandit -r src`
   - 掃描行數（Bandit 計算）：11578
   - Issues by severity：Low 63 / Medium 0 / High 0
   - Issues by confidence：Medium 6 / High 57
   - 備註：Bandit 在「有任何 issue」時會以 exit code 1 結束，這是正常行為。

## 重現方式

在專案根目錄執行：

```bash
python -m compileall -q src
uv tool run --isolated vulture src --min-confidence 80
uv tool run --isolated pylint src --disable=all --enable=duplicate-code --reports=n --score=n
uv tool run --isolated bandit -r src
```
