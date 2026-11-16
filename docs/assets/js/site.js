const THEME_STORAGE_KEY = "theme";

function initSiteThemeSwitcher() {
  const meta = document.querySelector('meta[name="color-scheme"]');
  const toggleBtn = document.getElementById("site-theme-toggle");
  const labelEl = document.getElementById("site-theme-label");
  if (!meta || !toggleBtn) return;

  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

  function readSavedTheme() {
    try {
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      return saved === "light" || saved === "dark" ? saved : null;
    } catch {
      return null;
    }
  }

  function getEffectiveTheme(saved) {
    if (saved === "light" || saved === "dark") return saved;
    return darkQuery.matches ? "dark" : "light";
  }

  function syncThemeUI() {
    const saved = readSavedTheme();
    const effective = getEffectiveTheme(saved);
    meta.setAttribute("content", saved || "light dark");

    if (labelEl) {
      labelEl.textContent = effective === "dark" ? "深色" : "淺色";
    }
    toggleBtn.setAttribute("aria-pressed", effective === "dark" ? "true" : "false");
    toggleBtn.setAttribute(
      "aria-label",
      effective === "dark"
        ? "目前為深色主題，點擊切換為淺色"
        : "目前為淺色主題，點擊切換為深色"
    );
  }

  toggleBtn.addEventListener("click", () => {
    const current = getEffectiveTheme(readSavedTheme());
    const next = current === "dark" ? "light" : "dark";
    const systemTheme = darkQuery.matches ? "dark" : "light";

    try {
      if (next === systemTheme) {
        localStorage.removeItem(THEME_STORAGE_KEY);
      } else {
        localStorage.setItem(THEME_STORAGE_KEY, next);
      }
    } catch {
      // 忽略無痕模式或儲存空間受限錯誤
    }
    syncThemeUI();
  });

  window.addEventListener("storage", (e) => {
    if (e.key === THEME_STORAGE_KEY || e.key === null) {
      syncThemeUI();
    }
  });

  darkQuery.addEventListener("change", () => {
    syncThemeUI();
  });

  syncThemeUI();
}

function initResponsiveNavbar() {
  const header = document.getElementById("site-header");
  const toggle = document.getElementById("site-nav-toggle");
  const menu = document.getElementById("site-nav-menu");
  if (!header || !toggle || !menu) return;

  // 寬窄切換由 CSS（@media width >= 54rem）處理；此處只同步 aria 並在變寬時收起 popover
  menu.addEventListener("toggle", (e) => {
    toggle.setAttribute("aria-expanded", String(e.newState === "open"));
  });

  matchMedia("(width >= 54rem)").addEventListener("change", (e) => {
    if (e.matches && menu.matches(":popover-open")) menu.hidePopover();
  });

  menu.addEventListener("click", (e) => {
    if (e.target instanceof Element && e.target.closest("a") && menu.matches(":popover-open")) {
      menu.hidePopover();
    }
  });

  // 捲動隱藏頂部列：支援 scroll-state 查詢時由 CSS 處理，否則以 JS 備援
  if (!CSS.supports("container-type", "scroll-state")) {
    let lastY = window.scrollY;
    addEventListener(
      "scroll",
      () => {
        const y = scrollY;
        if (y <= 40 || y < lastY - 4) header.classList.remove("is-hidden");
        else if (y > lastY + 12 && y > 88) header.classList.add("is-hidden");
        lastY = y;
      },
      { passive: true }
    );
  }

  // Scrollspy 降級方案（不支援 CSS scroll-target-group 時改以 IntersectionObserver 更新 aria-current）
  if (!CSS.supports("scroll-target-group", "auto")) {
    const pairs = [...menu.querySelectorAll('a[href^="#"]')]
      .map((link) => ({ link, sec: document.getElementById(link.hash.slice(1)) }))
      .filter((pair) => pair.sec);
    const visibleIds = new Set();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visibleIds.add(entry.target.id);
          else visibleIds.delete(entry.target.id);
        }
        const active = pairs.find((pair) => visibleIds.has(pair.sec.id));
        if (!active) return;
        for (const pair of pairs) {
          if (pair === active) pair.link.setAttribute("aria-current", "true");
          else pair.link.removeAttribute("aria-current");
        }
      },
      { rootMargin: "-20% 0px -65% 0px" }
    );
    pairs.forEach((pair) => observer.observe(pair.sec));
  }
}

function initCopyButtons() {
  const timers = new WeakMap();

  function reportCopy(btn, ok, msg) {
    const status = btn.nextElementSibling;
    const prevTimer = timers.get(btn);
    if (prevTimer) clearTimeout(prevTimer);

    btn.toggleAttribute("data-copied", ok);
    btn.toggleAttribute("data-failed", !ok);

    if (status && status.classList.contains("copy-status")) {
      const sameAsPrev = status.textContent === msg;
      const spokenMsg = sameAsPrev ? `${msg}\u00A0` : msg;
      status.textContent = "";
      requestAnimationFrame(() => {
        status.textContent = spokenMsg;
      });
    }

    timers.set(
      btn,
      setTimeout(() => {
        btn.removeAttribute("data-copied");
        btn.removeAttribute("data-failed");
        if (status && status.classList.contains("copy-status")) {
          status.textContent = "";
        }
      }, 2000)
    );
  }

  async function handleCopy(btn, target) {
    if (!btn || !target) return;
    const content = (target.innerText || target.textContent || "").trim();
    if (!content) return;

    try {
      await navigator.clipboard.writeText(content);
      reportCopy(btn, true, "已複製");
    } catch {
      reportCopy(btn, false, "複製失敗");
    }
  }

  const targets = new Set();
  document.querySelectorAll('.copy-btn[command="--copy"]').forEach((btn) => {
    const target = document.getElementById(btn.getAttribute("commandfor") ?? "");
    if (!target || targets.has(target)) return;
    targets.add(target);
    target.addEventListener("command", (e) => {
      if (e.command === "--copy" && e.source instanceof HTMLButtonElement && e.source.classList.contains("copy-btn")) {
        handleCopy(e.source, target);
      }
    });
  });
}

function initLightbox() {
  const dialog = document.getElementById("screenshot-lightbox");
  if (!dialog) return;

  const titleEl = document.getElementById("lightbox-title");
  const imgEl = document.getElementById("lightbox-img");
  const descEl = document.getElementById("lightbox-desc");
  function updateDialogContent(btn) {
    const src = btn.dataset.shotSrc || "";
    const title = btn.dataset.shotTitle || "畫面預覽";
    const desc = btn.dataset.shotDesc || "";
    const innerImg = btn.querySelector("img");

    if (titleEl) titleEl.textContent = title;
    if (descEl) descEl.textContent = desc;
    if (imgEl && src) {
      imgEl.src = src;
      imgEl.alt = innerImg ? innerImg.alt : title;
      if (innerImg && innerImg.width && innerImg.height) {
        imgEl.width = innerImg.width;
        imgEl.height = innerImg.height;
      }
    }
  }

  dialog.addEventListener("command", (e) => {
    if (e.command === "show-modal" && e.source instanceof HTMLElement) updateDialogContent(e.source);
  });

  dialog.addEventListener("close", () => {
    if (imgEl) imgEl.removeAttribute("src");
  });
}

initSiteThemeSwitcher();
initResponsiveNavbar();
initCopyButtons();
initLightbox();

// 模擬器（約 150 KB）僅在接近視窗時才載入，首屏不解析
const simulatorSection = document.getElementById("simulator");
if (simulatorSection) {
  const observer = new IntersectionObserver(
    async ([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      try {
        const { initWinUiSimulator } = await import("./simulator/index.js");
        initWinUiSimulator();
      } catch (err) {
        console.error("模擬器載入失敗", err);
      }
    },
    { rootMargin: "800px 0px" }
  );
  observer.observe(simulatorSection);
}
