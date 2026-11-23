/** 以非同步剪貼簿 API 寫入純文字，回傳是否成功（不支援或權限遭拒時為 false） */
export async function copyPlainText(text) {
  if (!navigator.clipboard?.writeText) return false;
  try {
    await navigator.clipboard.writeText(String(text ?? ""));
    return true;
  } catch {
    return false;
  }
}
