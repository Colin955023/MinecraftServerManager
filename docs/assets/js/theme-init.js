// 於首次繪製前同步套用已儲存的主題，避免閃爍
try {
  const saved = localStorage.getItem("theme");
  if (saved === "light" || saved === "dark") {
    document.querySelector('meta[name="color-scheme"]').content = saved;
  }
} catch {
  // 儲存空間不可用時沿用系統主題
}
