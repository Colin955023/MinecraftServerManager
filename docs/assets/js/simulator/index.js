import {
  DANGEROUS_JVM_PREFIXES,
  DEFAULT_PROPERTIES,
  JVM_PRESETS_G1,
  JVM_PRESETS_ZGC,
  LOADER_VERSIONS,
  MC_JAVA_MAP,
  MODRINTH_CATALOG,
  SYSTEM_MEMORY_MB,
  createInitialState
} from "./data.js";
import { escHtml, formatDuration, naturalCompare, nowDateTimeStr, nowTimeStr } from "./util.js";

const INFOBAR_ICONS = { success: "✓", warn: "⚠", error: "✕", info: "ℹ" };

export function initWinUiSimulator() {
  const app = document.getElementById("winui-app");
  if (!app) return;

  const infoBarHost = document.getElementById("winui-infobar-host");
  const quickModalBtns = document.querySelectorAll("[data-sim-open-modal]");
  const navButtons = document.querySelectorAll(".winui-nav-btn[data-sim-nav]");
  const pages = document.querySelectorAll(".winui-page[data-sim-page]");

  const modalBackdrop = document.getElementById("winui-modal-backdrop");
  const modalDialog = document.getElementById("winui-modal-dialog");
  const modalTitle = document.getElementById("winui-modal-title");
  const modalBody = document.getElementById("winui-modal-body");
  const modalFooter = document.getElementById("winui-modal-footer");
  const modalClose = document.getElementById("winui-modal-close");
  const contextMenu = document.getElementById("winui-context-menu");


  const state = createInitialState();

  function showInfoBar(title, message, level = "info") {
    if (!infoBarHost) return;
    const bar = document.createElement("div");
    bar.className = "winui-infobar";
    bar.dataset.level = level in INFOBAR_ICONS ? level : "info";
    bar.title = "點選關閉通知";
    bar.innerHTML = `<strong class="winui-infobar-icon">${INFOBAR_ICONS[bar.dataset.level]}</strong>
      <div><div class="u-bold">${escHtml(title)}</div><div class="winui-sub-label u-text">${escHtml(message)}</div></div>`;
    bar.addEventListener("click", () => bar.remove());
    infoBarHost.appendChild(bar);
    setTimeout(() => {
      bar.remove();
    }, 4200);
  }

  function getSelectedServer() {
    return state.servers.find((s) => s.id === state.selectedServerId) || null;
  }

  function ensureSelectedServerForModal() {
    if (getSelectedServer()) return getSelectedServer();
    if (state.servers.length === 0) return null;
    state.selectedServerId = state.servers[0].id;
    return state.servers[0];
  }

  // 右鍵選單為 popover="auto"：原生處理點選外部與 Esc 關閉，並位於頂層
  function hideContextMenu() {
    if (contextMenu.matches(":popover-open")) contextMenu.hidePopover();
  }

  function showContextMenuAt(x, y, items) {
    contextMenu.replaceChildren(
      ...items.map((item) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = item.danger ? "winui-context-item is-danger" : "winui-context-item";
        btn.setAttribute("role", "menuitem");
        btn.textContent = item.label;
        btn.addEventListener("click", () => {
          hideContextMenu();
          item.onClick();
        });
        return btn;
      })
    );

    if (!contextMenu.matches(":popover-open")) contextMenu.showPopover();
    const menuRect = contextMenu.getBoundingClientRect();
    const left = Math.max(8, Math.min(x, window.innerWidth - menuRect.width - 8));
    const top = Math.max(8, Math.min(y, window.innerHeight - menuRect.height - 8));
    contextMenu.style.left = `${left}px`;
    contextMenu.style.top = `${top}px`;
    contextMenu.querySelector("button")?.focus();
  }

  function switchPage(pageId) {
    closeModal();
    hideContextMenu();
    state.activePage = pageId;

    pages.forEach((p) => {
      p.hidden = p.dataset.simPage !== pageId;
    });
    navButtons.forEach((btn) => {
      if (btn.dataset.simNav === pageId) {
        btn.setAttribute("aria-current", "page");
      } else {
        btn.removeAttribute("aria-current");
      }
    });

    if (pageId === "manage") {
      renderServerTable();
      renderServerDetails();
    } else if (pageId === "mods") {
      syncModServerOptions();
      renderModsTable();
      renderOnlineModsPane();
    }
  }

  // 模擬視窗以非強制回應 <dialog> 呈現於模擬器內；開啟時背景設 inert，關閉後還原焦點
  const shell = app.querySelector(".winui-shell");

  function openModal({ title, size = "", locked = false, render }) {
    hideContextMenu();
    modalDialog.className = `winui-modal-dialog${size ? ` ${size}` : ""}`;
    modalTitle.textContent = title;
    modalBody.replaceChildren();
    modalFooter.replaceChildren();
    modalClose.disabled = locked;
    const opener = state.activeModal ? state.activeModal.opener : document.activeElement;
    state.activeModal = { locked, opener };
    shell.inert = true;
    modalBackdrop.hidden = false;
    if (!modalDialog.open) modalDialog.show();
    render({ body: modalBody, footer: modalFooter, setTitle: (t) => (modalTitle.textContent = t) });
  }

  function closeModal() {
    const active = state.activeModal;
    if (!active) return;
    active.onCleanup?.();
    state.activeModal = null;
    modalDialog.close();
    modalBackdrop.hidden = true;
    shell.inert = false;
    modalBody.replaceChildren();
    modalFooter.replaceChildren();
    if (active.opener?.isConnected) active.opener.focus();
  }

  modalClose.addEventListener("click", () => {
    if (state.activeModal && !state.activeModal.locked) closeModal();
  });

  modalBackdrop.addEventListener("click", (e) => {
    if (e.target === modalBackdrop && state.activeModal && !state.activeModal.locked) closeModal();
  });

  function showConfirmDialog({ title, message, primaryText = "確定", primaryDanger = false, secondaryText = null, closeText = "取消" }) {
    return new Promise((resolve) => {
      openModal({
        title,
        render({ body, footer }) {
          const p = document.createElement("p");
          p.style.whiteSpace = "pre-line";
          p.style.fontSize = "0.9rem";
          p.textContent = message;
          body.appendChild(p);

          const spacer = document.createElement("span");
          footer.appendChild(spacer);

          const btnGroup = document.createElement("div");
          btnGroup.className = "winui-input-row";

          if (closeText) {
            const cancelBtn = document.createElement("button");
            cancelBtn.type = "button";
            cancelBtn.className = "winui-btn";
            cancelBtn.textContent = closeText;
            cancelBtn.addEventListener("click", () => {
              closeModal();
              resolve(null);
            });
            btnGroup.appendChild(cancelBtn);
          }

          if (secondaryText) {
            const secBtn = document.createElement("button");
            secBtn.type = "button";
            secBtn.className = "winui-btn";
            secBtn.textContent = secondaryText;
            secBtn.addEventListener("click", () => {
              closeModal();
              resolve(false);
            });
            btnGroup.appendChild(secBtn);
          }

          const okBtn = document.createElement("button");
          okBtn.type = "button";
          okBtn.className = `winui-btn ${primaryDanger ? "winui-btn-danger" : "winui-btn-accent"}`;
          okBtn.textContent = primaryText;
          okBtn.addEventListener("click", () => {
            closeModal();
            resolve(true);
          });
          btnGroup.appendChild(okBtn);
          footer.appendChild(btnGroup);
        }
      });
    });
  }

  // =====================================================
  // Page 1: CreateServerView
  // =====================================================
  const createNameEl = document.getElementById("sim-name");
  const createJavaEl = document.getElementById("sim-java");
  const createLoaderEl = document.getElementById("sim-loader");
  const createLoaderVerEl = document.getElementById("sim-loader-ver");
  const reloadLoaderVerBtn = document.getElementById("sim-reload-loader-ver");
  const createMcVerEl = document.getElementById("sim-mc-ver");
  const reloadMcVerBtn = document.getElementById("sim-reload-mc-ver");
  const minMemEl = document.getElementById("sim-min-mem");
  const maxMemEl = document.getElementById("sim-max-mem");
  const memWarnEl = document.getElementById("sim-mem-warning");
  const jvmSummaryEl = document.getElementById("sim-jvm-summary");
  const createStatusEl = document.getElementById("sim-create-status");
  const resetCreateBtn = document.getElementById("sim-reset-create");
  const submitCreateBtn = document.getElementById("sim-submit-create");

  function getRequiredJavaMajor(mcVer) {
    return MC_JAVA_MAP[mcVer] || 21;
  }

  function syncCreateFormState() {
    const loader = createLoaderEl ? createLoaderEl.value : "Paper";
    const mcVer = createMcVerEl ? createMcVerEl.value : "1.21.4";
    const versions = LOADER_VERSIONS[loader] || ["最新穩定版"];

    if (createLoaderVerEl) {
      const prev = createLoaderVerEl.value;
      createLoaderVerEl.innerHTML = "";
      versions.forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = v;
        createLoaderVerEl.appendChild(opt);
      });
      if (versions.includes(prev)) {
        createLoaderVerEl.value = prev;
      }
      // 真實行為：僅 Forge 與 NeoForge 可手動挑選載入器版本
      const isLoaderVerEnabled = loader === "Forge" || loader === "NeoForge";
      createLoaderVerEl.disabled = !isLoaderVerEnabled;
    }

    if (reloadMcVerBtn) {
      // 真實行為：IsMinecraftVersionReloadEnabled = !IsPaperSelected
      reloadMcVerBtn.disabled = loader === "Paper";
    }

    if (createNameEl && !state.createNameManuallyEdited) {
      createNameEl.value = `${loader} ${mcVer}`;
    }

    syncJvmSummary();
    validateCreateMemory();
  }

  function syncJvmSummary() {
    if (!jvmSummaryEl) return;
    const mcVer = createMcVerEl ? createMcVerEl.value : "1.21.4";
    const major = getRequiredJavaMajor(mcVer);
    if (state.customJvmArgs && state.customJvmArgs.length > 0) {
      jvmSummaryEl.textContent = `已自訂 ${state.customJvmArgs.length} 項 JVM 啟動參數`;
    } else if (major >= 21) {
      jvmSummaryEl.textContent = "使用系統建議 JVM 參數 (ZGC)";
    } else {
      jvmSummaryEl.textContent = "使用系統建議 JVM 參數 (G1GC)";
    }
  }

  function validateCreateMemory() {
    if (!minMemEl || !maxMemEl || !memWarnEl) return true;
    const minRaw = minMemEl.value.trim();
    const maxRaw = maxMemEl.value.trim();
    const maxVal = Number.parseInt(maxRaw, 10);
    const minVal = minRaw === "" ? null : Number.parseInt(minRaw, 10);

    let msg = "";
    let isError = false;
    if (!maxRaw || Number.isNaN(maxVal) || maxVal < 512) {
      msg = "最大記憶體 (-Xmx) 至少需為 512 MB";
      isError = true;
    } else if (minVal !== null && (Number.isNaN(minVal) || minVal <= 0)) {
      msg = "最小記憶體若不留空，必須大於 0 MB";
      isError = true;
    } else if (minVal !== null && minVal > maxVal) {
      msg = "最小記憶體不可大於最大記憶體";
      isError = true;
    } else if (maxVal > SYSTEM_MEMORY_MB * 0.85) {
      msg = `提醒：設定的 ${maxVal} MB 接近本機偵測總記憶體 (${SYSTEM_MEMORY_MB} MB)，建議保留餘裕給作業系統`;
      isError = false;
    }

    memWarnEl.textContent = msg;
    memWarnEl.hidden = msg === "";
    memWarnEl.style.color = isError ? "var(--danger-fg)" : "var(--warning-fg)";
    return !isError;
  }

  if (createNameEl) {
    createNameEl.addEventListener("input", () => {
      state.createNameManuallyEdited = createNameEl.value.trim().length > 0;
    });
  }
  if (createLoaderEl) {
    createLoaderEl.addEventListener("change", syncCreateFormState);
  }
  if (createMcVerEl) {
    createMcVerEl.addEventListener("change", syncCreateFormState);
  }
  if (minMemEl) minMemEl.addEventListener("input", validateCreateMemory);
  if (maxMemEl) maxMemEl.addEventListener("input", validateCreateMemory);

  if (reloadLoaderVerBtn) {
    reloadLoaderVerBtn.addEventListener("click", () => {
      const loader = createLoaderEl ? createLoaderEl.value : "Paper";
      if (createStatusEl) createStatusEl.textContent = `已重新整理 ${loader} 版本清單`;
      showInfoBar("已重新整理載入器版本", `從官方中繼資料更新 ${loader} 可用版本清單。`, "info");
    });
  }

  if (reloadMcVerBtn) {
    reloadMcVerBtn.addEventListener("click", () => {
      if (createStatusEl) createStatusEl.textContent = "已重新載入 Mojang 官方版本目錄";
      showInfoBar("已重新整理 Minecraft 版本", "已自 Mojang Version Manifest V2 同步穩定版本。", "info");
    });
  }

  if (resetCreateBtn) {
    resetCreateBtn.addEventListener("click", async () => {
      const ok = await showConfirmDialog({
        title: "重設表單",
        message: "確定要重設建立伺服器頁面的所有欄位與 JVM 自訂參數嗎？",
        primaryText: "確定重設",
        primaryDanger: true
      });
      if (!ok) return;
      state.createNameManuallyEdited = false;
      state.customJvmArgs = null;
      if (createLoaderEl) createLoaderEl.value = "Paper";
      if (createMcVerEl) createMcVerEl.value = "1.21.4";
      if (createJavaEl) createJavaEl.value = "";
      if (minMemEl) minMemEl.value = "1024";
      if (maxMemEl) maxMemEl.value = "2048";
      syncCreateFormState();
      showInfoBar("表單已重設", "已還原為預設 Paper 建立設定。", "info");
    });
  }

  if (submitCreateBtn) {
    submitCreateBtn.addEventListener("click", () => {
      const name = (createNameEl?.value || "").trim();
      if (!name) {
        showInfoBar("驗證失敗", "伺服器名稱不能為空。", "warn");
        return;
      }
      if (state.servers.some((s) => s.name.toLowerCase() === name.toLowerCase())) {
        showInfoBar("名稱重複", `伺服器「${name}」已存在於清單中。`, "warn");
        return;
      }
      if (!validateCreateMemory()) {
        showInfoBar("記憶體設定無效", memWarnEl?.textContent || "請檢查記憶體設定。", "warn");
        return;
      }

      const loader = createLoaderEl ? createLoaderEl.value : "Paper";
      const mcVer = createMcVerEl ? createMcVerEl.value : "1.21.4";
      const reqMajor = getRequiredJavaMajor(mcVer);
      const minMem = minMemEl?.value.trim() ? Number.parseInt(minMemEl.value, 10) : null;
      const maxMem = Number.parseInt(maxMemEl?.value || "2048", 10);

      openModal({
        title: `建立與初始化伺服器 — ${name}`,
        locked: true,
        render({ body, footer }) {
          const p = document.createElement("div");
          p.style.fontSize = "0.88rem";
          p.textContent = `步驟 1/2：正在驗證 Java ${reqMajor} 與下載 ${loader} ${mcVer} 核心檔...`;
          const track = document.createElement("div");
          track.className = "winui-progress-track";
          const fill = document.createElement("div");
          fill.className = "winui-progress-fill";
          fill.style.inlineSize = "35%";
          track.appendChild(fill);
          body.append(p, track);

          setTimeout(() => {
            fill.style.inlineSize = "75%";
            p.textContent = "步驟 2/2：寫入統一啟動腳本 start_server.bat、同意 eula.txt 並產生 server.properties...";
          }, 420);

          setTimeout(() => {
            const newServer = {
              id: name,
              name,
              version: mcVer,
              loader,
              running: false,
              ready: false,
              sizeBytes: 62400000,
              size: "59.5 MB",
              created: nowDateTimeStr(),
              modified: nowDateTimeStr(),
              backupPath: "",
              relPath: name,
              minMem,
              maxMem,
              javaMajor: reqMajor,
              uptimeSec: 0,
              ramUsage: "-",
              backups: [],
              onlinePlayers: [],
              consoleLogs: [`[${nowTimeStr()}] [系統] 已完成 ${loader} ${mcVer} 初始化並同意 eula.txt。`],
              cmdHistory: [],
              properties: DEFAULT_PROPERTIES.map((prop) => ({ ...prop })),
              usercache: [],
              ops: [],
              whitelist: [],
              bannedPlayers: [],
              bannedIps: []
            };
            state.servers.push(newServer);
            if (loader !== "Paper" && !state.modsByServer[name]) {
              state.modsByServer[name] = [];
            }
            state.selectedServerId = name;
            state.createNameManuallyEdited = false;
            state.customJvmArgs = null;
            closeModal();
            switchPage("manage");
            showInfoBar("建立伺服器完成", `已建立「${name} (${loader} ${mcVer})」並選取於管理清單。`, "success");
          }, 900);
        }
      });
    });
  }

  function openManageJavaDialog() {
    const mcVer = createMcVerEl ? createMcVerEl.value : "1.21.4";
    const reqMajor = getRequiredJavaMajor(mcVer);
    let selectedJavaIdx = Math.max(
      0,
      state.installedJavas.findIndex((j) => j.major === reqMajor)
    );

    openModal({
      title: "本機 Java 執行環境管理",
      size: "is-medium",
      render({ body, footer }) {
        body.innerHTML = `
          <div class="winui-card winui-setting-row">
            <div>
              <div class="u-bold">目前 Minecraft 版本：${escHtml(mcVer)} · 指定需求：Java ${reqMajor}</div>
              <div class="winui-sub-label">過濾 Windows javapath shim 並檢查 PE 標頭 64 位元執行檔</div>
            </div>
            <div class="winui-actions-wrap">
              <button type="button" class="winui-btn" id="dlg-java-autodetect">自動偵測配對</button>
              <button type="button" class="winui-btn" id="dlg-java-install">⬇️ winget 安裝 Java ${reqMajor}</button>
            </div>
          </div>
          <div class="winui-table-scroll">
            <table class="winui-table">
              <thead>
                <tr><th>主要版本</th><th>發行廠商</th><th>相容狀態</th><th>執行檔路徑</th></tr>
              </thead>
              <tbody id="dlg-java-tbody"></tbody>
            </table>
          </div>`;

        const tbody = body.querySelector("#dlg-java-tbody");
        function renderRows() {
          tbody.innerHTML = "";
          state.installedJavas.forEach((j, idx) => {
            const compat = j.major === reqMajor ? "✓ 符合需求（建議）" : "其他版本";
            const tr = document.createElement("tr");
            tr.setAttribute("aria-selected", idx === selectedJavaIdx ? "true" : "false");
            tr.innerHTML = `<td>Java ${j.major}</td><td>${escHtml(j.vendor)}</td>
              <td class="${j.major === reqMajor ? "status-running" : ""}">${compat}</td>
              <td><code>${escHtml(j.path)}</code></td>`;
            tr.addEventListener("click", () => {
              selectedJavaIdx = idx;
              renderRows();
            });
            tr.addEventListener("dblclick", () => {
              if (createJavaEl) createJavaEl.value = j.path;
              closeModal();
              showInfoBar("已套用 Java 路徑", j.path, "success");
            });
            tbody.appendChild(tr);
          });
        }
        renderRows();

        body.querySelector("#dlg-java-autodetect").addEventListener("click", () => {
          const found = state.installedJavas.findIndex((j) => j.major === reqMajor);
          if (found >= 0) {
            selectedJavaIdx = found;
            renderRows();
            showInfoBar("自動偵測完成", `已配對相容的 Java ${reqMajor} 64 位元執行檔。`, "success");
          } else {
            showInfoBar("缺少相容版本", `尚未偵測到 Java ${reqMajor}，可按右側 winget 安裝。`, "warn");
          }
        });

        body.querySelector("#dlg-java-install").addEventListener("click", () => {
          if (!state.installedJavas.some((j) => j.major === reqMajor)) {
            state.installedJavas.push({
              major: reqMajor,
              vendor: "Eclipse Adoptium (winget)",
              path: `C:\\Program Files\\Eclipse Adoptium\\jdk-${reqMajor}.0.5\\bin\\java.exe`
            });
          }
          selectedJavaIdx = state.installedJavas.findIndex((j) => j.major === reqMajor);
          renderRows();
          showInfoBar("winget 安裝完成", `Java ${reqMajor} 已加入偵測清單。`, "success");
        });

        const left = document.createElement("span");
        left.className = "winui-sub-label";
        left.textContent = "點兩下列或點「套用選定 Java」將路徑填入表單";
        const right = document.createElement("div");
        right.className = "winui-input-row";
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "winui-btn";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", closeModal);
        const applyBtn = document.createElement("button");
        applyBtn.type = "button";
        applyBtn.className = "winui-btn winui-btn-accent";
        applyBtn.textContent = "套用選定 Java";
        applyBtn.addEventListener("click", () => {
          const chosen = state.installedJavas[selectedJavaIdx];
          if (chosen && createJavaEl) {
            createJavaEl.value = chosen.path;
            showInfoBar("已套用 Java 路徑", chosen.path, "success");
          }
          closeModal();
        });
        right.append(cancelBtn, applyBtn);
        footer.append(left, right);
      }
    });
  }

  function openJvmArgsDialog() {
    const mcVer = createMcVerEl ? createMcVerEl.value : "1.21.4";
    const major = getRequiredJavaMajor(mcVer);
    const presets = major >= 21 ? JVM_PRESETS_ZGC : JVM_PRESETS_G1;
    const presetMap = new Set(presets.map((p) => p.opt));
    const checkedOpts = new Set(
      state.customJvmArgs === null
        ? presets.map((p) => p.opt)
        : state.customJvmArgs.filter((a) => presetMap.has(a))
    );
    const customInitial = (state.customJvmArgs || []).filter((a) => !presetMap.has(a));
    let hasCustom = customInitial.length > 0;
    let customText = customInitial.join(" ");

    openModal({
      title: "JVM 參數設定",
      render({ body, footer }) {
        const info = document.createElement("p");
        info.className = "winui-sub-label";
        info.textContent =
          major >= 21
            ? `目前偵測為 Java ${major}，已自動套用 ZGC 低延遲最佳化設定。`
            : `目前偵測為 Java ${major}，已自動套用 G1GC (Aikar's Flags) 最佳化設定。`;

        const card = document.createElement("div");
        card.className = "winui-card";
        card.style.display = "flex";
        card.style.flexDirection = "column";
        card.style.gap = "0.45rem";

        function renderPresetCheckboxes() {
          card.innerHTML = "";
          presets.forEach((p) => {
            const label = document.createElement("label");
            label.className = "winui-input-row";
            label.title = p.desc;
            label.style.fontSize = "0.86rem";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = checkedOpts.has(p.opt);
            cb.addEventListener("change", () => {
              if (cb.checked) checkedOpts.add(p.opt);
              else checkedOpts.delete(p.opt);
            });
            label.append(cb, Object.assign(document.createElement("code"), { textContent: p.opt }), Object.assign(document.createElement("span"), { className: "winui-sub-label", textContent: p.desc }));
            card.appendChild(label);
          });
        }
        renderPresetCheckboxes();

        const customWrap = document.createElement("div");
        customWrap.style.display = "flex";
        customWrap.style.flexDirection = "column";
        customWrap.style.gap = "0.4rem";
        const customLabel = document.createElement("label");
        customLabel.className = "winui-input-row";
        const customCb = document.createElement("input");
        customCb.type = "checkbox";
        customCb.checked = hasCustom;
        customLabel.append(customCb, document.createTextNode("其他自訂參數（由 JvmOptionPolicy 過濾可執行外部命令之選項）"));
        const customInput = document.createElement("input");
        customInput.className = "winui-input";
        customInput.type = "text";
        customInput.disabled = !hasCustom;
        customInput.value = customText;
        customInput.placeholder = "例如：-Dfile.encoding=UTF-8";
        customCb.addEventListener("change", () => {
          hasCustom = customCb.checked;
          customInput.disabled = !hasCustom;
        });
        customWrap.append(customLabel, customInput);

        body.append(info, card, customWrap);

        const resetBtn = document.createElement("button");
        resetBtn.type = "button";
        resetBtn.className = "winui-btn";
        resetBtn.textContent = "重設為建議預設";
        resetBtn.addEventListener("click", () => {
          checkedOpts.clear();
          presets.forEach((p) => checkedOpts.add(p.opt));
          customCb.checked = false;
          hasCustom = false;
          customInput.value = "";
          customInput.disabled = true;
          renderPresetCheckboxes();
        });

        const right = document.createElement("div");
        right.className = "winui-input-row";
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "winui-btn";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", closeModal);
        const applyBtn = document.createElement("button");
        applyBtn.type = "button";
        applyBtn.className = "winui-btn winui-btn-accent";
        applyBtn.textContent = "套用";
        applyBtn.addEventListener("click", () => {
          const finalArgs = [...checkedOpts];
          const rejected = [];
          if (hasCustom && customInput.value.trim()) {
            customInput.value
              .trim()
              .split(/\s+/)
              .forEach((tok) => {
                const bad = DANGEROUS_JVM_PREFIXES.some((prefix) => tok.toLowerCase().startsWith(prefix.toLowerCase()));
                if (bad) rejected.push(tok);
                else finalArgs.push(tok);
              });
          }
          state.customJvmArgs = finalArgs;
          syncJvmSummary();
          closeModal();
          if (rejected.length > 0) {
            showInfoBar("已排除危險 JVM 參數", `JvmOptionPolicy 已阻擋：${rejected.join(", ")}`, "warn");
          } else {
            showInfoBar("JVM 參數已更新", `共套用 ${finalArgs.length} 項啟動參數。`, "success");
          }
        });
        right.append(cancelBtn, applyBtn);
        footer.append(resetBtn, right);
      }
    });
  }

  // =====================================================
  // Page 2: ManageServerView
  // =====================================================
  const serversRootInput = document.getElementById("sim-servers-root");
  const serverTbody = document.getElementById("sim-server-tbody");
  const manageTableCard = document.getElementById("sim-manage-table-card");
  const manageUnselectedEl = document.getElementById("sim-manage-unselected");
  const manageSelectedEl = document.getElementById("sim-manage-selected");
  const detailsEl = document.getElementById("sim-server-details");
  const toggleRunBtn = document.getElementById("sim-toggle-run-btn");
  const playersManageBtn = document.getElementById("sim-players-btn");
  const manageStatusEl = document.getElementById("sim-manage-status");

  function updateSortIndicators(tableName) {
    const sortInfo = state.sortState[tableName];
    if (!sortInfo) return;
    document.querySelectorAll(`.winui-sort-btn[data-sort-table="${tableName}"]`).forEach((btn) => {
      const active = btn.dataset.sortKey === sortInfo.key;
      const ind = btn.querySelector(".sort-ind");
      if (ind) ind.textContent = active ? (sortInfo.dir === "asc" ? "▲" : "▼") : "";
      btn.closest("th")?.setAttribute("aria-sort", active ? (sortInfo.dir === "asc" ? "ascending" : "descending") : "none");
    });
  }

  function renderServerTable() {
    if (!serverTbody) return;
    if (serversRootInput) serversRootInput.value = state.serversRoot;

    const { key, dir } = state.sortState.servers;
    const mult = dir === "asc" ? 1 : -1;
    const sorted = [...state.servers].sort((a, b) => {
      if (key === "sizeBytes" || key === "backupsCount") {
        const av = key === "sizeBytes" ? a.sizeBytes : a.backups.length;
        const bv = key === "sizeBytes" ? b.sizeBytes : b.backups.length;
        return (av - bv) * mult;
      }
      if (key === "running") {
        return (Number(a.running) - Number(b.running)) * mult;
      }
      return naturalCompare(a[key], b[key]) * mult;
    });
    updateSortIndicators("servers");

    serverTbody.innerHTML = "";
    sorted.forEach((srv) => {
      const tr = document.createElement("tr");
      tr.setAttribute("aria-selected", srv.id === state.selectedServerId ? "true" : "false");
      const statusCls = srv.running ? "status-running" : "status-stopped";
      const statusText = srv.running ? "● 執行中" : "○ 已停止";
      const backupText = srv.backupPath
        ? srv.backups.length > 0
          ? `已備份 (${srv.backups.length} 份)`
          : "已設定 (0 份)"
        : "未設定備份資料夾";

      tr.innerHTML = `
        <td><strong>${escHtml(srv.name)}</strong></td>
        <td>${escHtml(srv.version)}</td>
        <td>${escHtml(srv.loader)}</td>
        <td class="${statusCls}">${statusText}</td>
        <td>${escHtml(srv.size)}</td>
        <td>${escHtml(srv.modified)}</td>
        <td>${escHtml(backupText)}</td>
        <td><code>${escHtml(srv.relPath)}</code></td>`;

      tr.tabIndex = 0;
      const selectRow = () => {
        state.selectedServerId = srv.id;
        renderServerTable();
        renderServerDetails();
      };

      tr.addEventListener("click", (e) => {
        e.stopPropagation();
        selectRow();
      });

      tr.addEventListener("dblclick", (e) => {
        e.stopPropagation();
        selectRow();
        openServerMonitorWindow(srv);
      });

      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectRow();
          serverTbody.querySelector('tr[aria-selected="true"]')?.focus();
        } else if (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey)) {
          e.preventDefault();
          const r = tr.getBoundingClientRect();
          tr.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: r.left + 24, clientY: r.bottom }));
        }
      });

      tr.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.selectedServerId = srv.id;
        renderServerTable();
        renderServerDetails();
        showContextMenuAt(e.clientX, e.clientY, [
          { label: "🧠 修改記憶體設定", onClick: () => openServerMemoryDialog(srv) },
          { label: "🔄 重新偵測伺服器", onClick: () => showInfoBar("重新偵測完成", `已重新檢查「${srv.name}」核心檔案與版本資訊。`, "success") },
          { label: "📂 開啟備份資料夾", onClick: () => handleOpenBackupFolder(srv) },
          { label: "📁 修改備份路徑", onClick: () => handleEditBackupPath(srv) }
        ]);
      });

      serverTbody.appendChild(tr);
    });
  }

  if (manageTableCard) {
    manageTableCard.addEventListener("click", (e) => {
      if (!e.target.closest("tbody tr") && !e.target.closest("th")) {
        state.selectedServerId = null;
        renderServerTable();
        renderServerDetails();
      }
    });
  }

  function renderServerDetails() {
    const srv = getSelectedServer();
    if (!manageUnselectedEl || !manageSelectedEl || !detailsEl) return;

    if (!srv) {
      manageUnselectedEl.hidden = false;
      manageSelectedEl.hidden = true;
      return;
    }

    manageUnselectedEl.hidden = true;
    manageSelectedEl.hidden = false;

    const absPath = `${state.serversRoot}\\${srv.relPath}`;
    const backupStatusText = srv.backupPath
      ? srv.backups.length > 0
        ? `已備份 (${srv.backups.length} 份)`
        : "已設定 (0 份)"
      : "未設定備份資料夾";
    const cells = [
      ["伺服器名稱：", srv.name],
      ["Minecraft 版本：", srv.version],
      ["載入器類型：", srv.loader],
      ["目前狀態：", srv.running ? "執行中" : "已停止"],
      ["目錄大小：", srv.size],
      ["記憶體配置：", `${srv.minMem ? `${srv.minMem}–` : ""}${srv.maxMem} MB`],
      ["備份狀況：", backupStatusText],
      ["外部備份路徑：", srv.backupPath || "(尚未設定)"],
      ["實體路徑：", absPath]
    ];

    detailsEl.innerHTML = cells
      .map(([k, v]) => `<div><span class="winui-kv-label">${escHtml(k)}</span><span class="winui-kv-val">${escHtml(v)}</span></div>`)
      .join("");

    if (toggleRunBtn) {
      toggleRunBtn.textContent = srv.running ? "停止" : "啟動";
      toggleRunBtn.className = `winui-btn ${srv.running ? "winui-btn-danger" : "winui-btn-accent"}`;
    }
    if (playersManageBtn) {
      playersManageBtn.disabled = srv.running;
    }
  }

  async function handleStartOrStopServer(srv, startTarget) {
    if (!srv) return;
    if (startTarget) {
      if (srv.running) return;
      if (state.prefs.autoBackupBeforeStart && srv.backupPath) {
        createBackupEntry(srv);
      }
      srv.running = true;
      srv.ready = false;
      srv.uptimeSec = 1;
      srv.ramUsage = `${Math.round(srv.maxMem * 0.45).toLocaleString()} MB`;
      srv.consoleLogs = [
        "[系統] 伺服器行程已啟動...",
        `[${nowTimeStr()}] [Server thread/INFO]: Starting minecraft server version ${srv.version} (${srv.loader})`
      ];
      renderServerTable();
      renderServerDetails();
      showInfoBar("啟動中", `正在啟動「${srv.name}」，就緒時將顯示連線通知。`, "info");

      setTimeout(() => {
        if (!srv.running) return;
        srv.ready = true;
        const port = srv.properties.find((p) => p.key === "server-port")?.val || "25565";
        srv.consoleLogs.push(`[${nowTimeStr()}] [Server thread/INFO]: Done (2.143s)! For help, type "help"`);
        srv.consoleLogs.push("[系統] 伺服器已就緒，完成載入！");
        if (state.activeModal && typeof state.activeModal.refreshMonitor === "function") {
          state.activeModal.refreshMonitor();
        }
        showInfoBar(`伺服器啟動成功 — ${srv.name}`, `已在連接埠 ${port} 開啟服務`, "success");
      }, 700);
    } else {
      if (!srv.running) return;
      srv.running = false;
      srv.ready = false;
      srv.uptimeSec = 0;
      srv.ramUsage = "-";
      srv.onlinePlayers = [];
      srv.consoleLogs.push(`[${nowTimeStr()}] [Server thread/INFO]: Stopping the server`);
      srv.consoleLogs.push(`[系統] 伺服器行程已安全結束（ExitCode: 0）。`);
      renderServerTable();
      renderServerDetails();
      if (state.activeModal && typeof state.activeModal.refreshMonitor === "function") {
        state.activeModal.refreshMonitor();
      }
      showInfoBar("已停止伺服器", `「${srv.name}」已完成存檔並正常結束。`, "info");
    }
  }

  function createBackupEntry(srv) {
    const stamp = nowDateTimeStr().replace(/[-:\s]/g, "").slice(0, 12);
    const entry = {
      fileName: `${srv.name}_${stamp}.zip`,
      size: `${Math.max(25, Math.round(srv.sizeBytes / 1048576 * 0.55))} MB`,
      created: nowDateTimeStr()
    };
    srv.backups.unshift(entry);
    while (srv.backups.length > state.prefs.retention) {
      srv.backups.pop();
    }
    return entry;
  }

  async function handleOpenBackupFolder(srv) {
    if (!srv.backupPath) {
      const ok = await showConfirmDialog({
        title: "尚未設定備份資料夾",
        message: `伺服器「${srv.name}」尚未設定自訂外部備份路徑。\n\n是否要立即指定備份資料夾？`,
        primaryText: "設定路徑"
      });
      if (ok) await handleEditBackupPath(srv);
      return;
    }
    showInfoBar("開啟備份資料夾", `目標路徑：${srv.backupPath}`, "info");
  }

  async function handleEditBackupPath(srv) {
    openModal({
      title: `選擇伺服器「${srv.name}」的外部備份資料夾`,
      render({ body, footer }) {
        const cur = srv.backupPath || `D:\\MC-Backups\\${srv.name}`;
        body.innerHTML = `<p class="winui-sub-label">備份必須存放於伺服器目錄之外的獨立外部資料夾，避免遞迴壓縮風險。</p>
          <label class="winui-label" for="dlg-backup-path">備份資料夾路徑：</label>
          <input id="dlg-backup-path" class="winui-input" type="text" value="${escHtml(cur)}">`;
        const pathEl = body.querySelector("#dlg-backup-path");
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "winui-btn";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", closeModal);
        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "winui-btn winui-btn-accent";
        saveBtn.textContent = "套用備份路徑";
        saveBtn.addEventListener("click", () => {
          const val = pathEl.value.trim();
          if (!val) {
            showInfoBar("路徑無效", "備份資料夾路徑不可為空。", "warn");
            return;
          }
          if (val.toLowerCase().startsWith(state.serversRoot.toLowerCase())) {
            showInfoBar("安全邊界攔截", "備份路徑不可位於伺服器存放主目錄內。", "warn");
            return;
          }
          srv.backupPath = val;
          closeModal();
          renderServerTable();
          renderServerDetails();
          showInfoBar("已更新備份資料夾", `${srv.name} → ${val}`, "success");
        });
        footer.append(document.createElement("span"), Object.assign(document.createElement("div"), { className: "winui-input-row" }));
        footer.lastChild.append(cancelBtn, saveBtn);
      }
    });
  }

  async function handleBackupServer(srv) {
    if (!srv) return;
    if (srv.running) {
      showInfoBar("無法備份", "伺服器正在執行中，請先停止伺服器後再備份。", "warn");
      return;
    }
    if (!srv.backupPath) {
      showInfoBar("請設定備份路徑", "伺服器尚未設定外部備份資料夾，請先設定儲存位置。", "warn");
      await handleEditBackupPath(srv);
      return;
    }
    const created = createBackupEntry(srv);
    renderServerTable();
    renderServerDetails();
    showInfoBar("備份建立成功", `已建立 ${created.fileName}（保留上限 ${state.prefs.retention} 份）。`, "success");
  }

  function openRestoreBackupDialog(srv) {
    if (!srv) return;
    if (!srv.backupPath) {
      showInfoBar("尚未設定備份資料夾", "請先透過右鍵選單「修改備份路徑」指定外部備份目錄。", "warn");
      return;
    }
    let selectedIdx = srv.backups.length > 0 ? 0 : -1;

    openModal({
      title: `備份還原與管理 — ${srv.name}`,
      size: "is-medium",
      render({ body, footer }) {
        body.innerHTML = `
          <p class="winui-sub-label">選擇備份存檔進行還原（具備 Staging 暫存 logs/ 與 crash-reports/ 交易保護與自動復原機制）</p>
          <div class="winui-table-scroll">
            <table class="winui-table">
              <thead><tr><th>備份檔案名稱</th><th>檔案大小</th><th>建立時間</th></tr></thead>
              <tbody id="dlg-restore-tbody"></tbody>
            </table>
          </div>
          <div id="dlg-restore-status" class="winui-sub-label"></div>
          <div id="dlg-restore-confirm" class="winui-form-warning" hidden></div>`;

        const tbody = body.querySelector("#dlg-restore-tbody");
        const statusEl = body.querySelector("#dlg-restore-status");
        const confirmEl = body.querySelector("#dlg-restore-confirm");
        let pendingDeleteIdx = -1;

        function clearDeleteConfirm() {
          pendingDeleteIdx = -1;
          confirmEl.hidden = true;
          confirmEl.innerHTML = "";
        }

        function renderList() {
          tbody.innerHTML = "";
          if (srv.backups.length === 0) {
            selectedIdx = -1;
            clearDeleteConfirm();
            statusEl.textContent = "此伺服器目前尚無任何備份檔案";
            return;
          }
          if (selectedIdx >= srv.backups.length) selectedIdx = srv.backups.length - 1;
          statusEl.textContent = `共找到 ${srv.backups.length} 份備份`;
          srv.backups.forEach((b, idx) => {
            const tr = document.createElement("tr");
            tr.setAttribute("aria-selected", idx === selectedIdx ? "true" : "false");
            tr.innerHTML = `<td>${escHtml(b.fileName)}</td><td>${escHtml(b.size)}</td><td>${escHtml(b.created)}</td>`;
            tr.addEventListener("click", () => {
              selectedIdx = idx;
              clearDeleteConfirm();
              renderList();
            });
            tbody.appendChild(tr);
          });
        }
        renderList();

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "winui-btn winui-btn-danger";
        delBtn.textContent = "刪除選取備份";
        delBtn.addEventListener("click", () => {
          if (selectedIdx < 0 || !srv.backups[selectedIdx]) return;
          if (pendingDeleteIdx === selectedIdx) return;
          pendingDeleteIdx = selectedIdx;
          const target = srv.backups[selectedIdx];
          confirmEl.hidden = false;
          confirmEl.innerHTML = "";
          const msg = document.createElement("span");
          msg.textContent = `確定要永久刪除「${target.fileName}」嗎？`;
          const actions = document.createElement("div");
          actions.className = "winui-input-row mt-1";
          const yesBtn = document.createElement("button");
          yesBtn.type = "button";
          yesBtn.className = "winui-btn winui-btn-danger";
          yesBtn.textContent = "確認刪除";
          yesBtn.addEventListener("click", () => {
            const idxToRemove = pendingDeleteIdx;
            const removed = srv.backups[idxToRemove];
            clearDeleteConfirm();
            if (!removed) return;
            srv.backups.splice(idxToRemove, 1);
            renderList();
            renderServerTable();
            renderServerDetails();
            showInfoBar("已刪除備份", removed.fileName, "info");
          });
          const noBtn = document.createElement("button");
          noBtn.type = "button";
          noBtn.className = "winui-btn";
          noBtn.textContent = "取消";
          noBtn.addEventListener("click", clearDeleteConfirm);
          actions.append(noBtn, yesBtn);
          confirmEl.append(msg, actions);
        });

        const right = document.createElement("div");
        right.className = "winui-input-row";
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "winui-btn";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", closeModal);
        const restoreBtn = document.createElement("button");
        restoreBtn.type = "button";
        restoreBtn.className = "winui-btn winui-btn-accent";
        restoreBtn.textContent = "開始還原";
        restoreBtn.addEventListener("click", () => {
          if (srv.running) {
            showInfoBar("無法還原", "伺服器正在執行中，請先停止後再進行還原。", "warn");
            return;
          }
          if (selectedIdx < 0 || !srv.backups[selectedIdx]) {
            showInfoBar("未選取備份", "請先選取要還原的備份檔案。", "warn");
            return;
          }
          const chosen = srv.backups[selectedIdx];
          closeModal();
          showInfoBar("備份還原完成", `已安全還原「${chosen.fileName}」，並已合併保存原有 logs/ 與 crash-reports/。`, "success");
        });
        right.append(cancelBtn, restoreBtn);
        footer.append(delBtn, right);
      }
    });
  }

  function openServerMemoryDialog(srv) {
    openModal({
      title: `🧠 修改伺服器記憶體設定 — ${srv.name}`,
      render({ body, footer }) {
        body.innerHTML = `
          <div class="winui-sub-label">目前伺服器：${escHtml(srv.name)} (${escHtml(srv.loader)} ${escHtml(srv.version)})</div>
          <div class="u-accent u-fs-84">系統實體記憶體：${SYSTEM_MEMORY_MB.toLocaleString()} MB</div>
          <div class="winui-card u-flex u-dir-col u-gap-60">
            <div>
              <label class="winui-label" for="dlg-srv-maxmem">最大記憶體（-Xmx，單位 MB）：</label>
              <input id="dlg-srv-maxmem" class="winui-input mt-1" type="number" value="${srv.maxMem}">
            </div>
            <div>
              <label class="winui-label" for="dlg-srv-minmem">最小初始記憶體（-Xms，單位 MB，可留空）：</label>
              <input id="dlg-srv-minmem" class="winui-input mt-1" type="number" value="${srv.minMem ?? ""}">
            </div>
          </div>
          <div id="dlg-srv-mem-err" class="winui-form-warning" hidden></div>`;

        const maxEl = body.querySelector("#dlg-srv-maxmem");
        const minEl = body.querySelector("#dlg-srv-minmem");
        const errEl = body.querySelector("#dlg-srv-mem-err");

        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "winui-btn";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", closeModal);
        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "winui-btn winui-btn-accent";
        saveBtn.textContent = "儲存設定";
        saveBtn.addEventListener("click", () => {
          const maxVal = Number.parseInt(maxEl.value, 10);
          const minRaw = minEl.value.trim();
          const minVal = minRaw === "" ? null : Number.parseInt(minRaw, 10);
          if (Number.isNaN(maxVal) || maxVal < 512) {
            errEl.textContent = "最大記憶體至少須為 512 MB";
            errEl.hidden = false;
            return;
          }
          if (minVal !== null && (Number.isNaN(minVal) || minVal <= 0 || minVal > maxVal)) {
            errEl.textContent = "最小記憶體須大於 0 且不可超過最大記憶體";
            errEl.hidden = false;
            return;
          }
          srv.maxMem = maxVal;
          srv.minMem = minVal;
          renderServerDetails();
          closeModal();
          showInfoBar("已更新記憶體設定", `StartScriptWriter 已同步寫入 -Xms/-Xmx (${maxVal} MB)。`, "success");
        });
        footer.append(document.createElement("span"), Object.assign(document.createElement("div"), { className: "winui-input-row" }));
        footer.lastChild.append(cancelBtn, saveBtn);
      }
    });
  }

  function openImportServerDialog() {
    let sourcePath = "";
    let mode = "copy";

    openModal({
      title: "匯入外部 Minecraft 伺服器",
      render({ body, footer }) {
        body.innerHTML = `
          <p class="winui-sub-label">支援從本機資料夾或 ZIP 壓縮檔匯入既有伺服器（可辨識 Vanilla、Paper、Fabric、Quilt、Forge、NeoForge）</p>
          <div>
            <label class="winui-label" for="dlg-imp-src">來源路徑（目錄或 .zip 檔）：</label>
            <div class="winui-input-row mt-1">
              <input id="dlg-imp-src" class="winui-input" type="text" placeholder="請選擇或輸入本機資料夾 / ZIP 路徑...">
              <button type="button" class="winui-btn" id="dlg-imp-zip">瀏覽 ZIP</button>
              <button type="button" class="winui-btn" id="dlg-imp-dir">瀏覽資料夾</button>
            </div>
          </div>
          <div>
            <label class="winui-label" for="dlg-imp-name">匯入後的伺服器名稱：</label>
            <input id="dlg-imp-name" class="winui-input mt-1" type="text" placeholder="例如 Vanilla-Classic">
          </div>
          <div>
            <div class="winui-label mb-1">匯入方式：</div>
            <div class="winui-input-row u-gap-120">
              <label class="winui-input-row"><input type="radio" name="dlg-imp-mode" value="copy" checked> 複製（保留原始來源）</label>
              <label class="winui-input-row"><input type="radio" name="dlg-imp-mode" value="move"> 遷移（匯入完成後移除原始來源）</label>
            </div>
          </div>
          <div id="dlg-imp-err" class="winui-form-warning" hidden></div>
          <div id="dlg-imp-move-confirm" class="winui-form-warning" hidden></div>`;

        const srcEl = body.querySelector("#dlg-imp-src");
        const nameEl = body.querySelector("#dlg-imp-name");
        const errEl = body.querySelector("#dlg-imp-err");
        const moveConfirmEl = body.querySelector("#dlg-imp-move-confirm");
        let moveConfirmed = false;
        const submitBtn = document.createElement("button");
        submitBtn.type = "button";
        submitBtn.className = "winui-btn winui-btn-accent";
        submitBtn.textContent = "開始匯入";

        function resetImportWarnings() {
          errEl.hidden = true;
          moveConfirmEl.hidden = true;
          moveConfirmEl.textContent = "";
          moveConfirmed = false;
          submitBtn.textContent = "開始匯入";
          submitBtn.className = "winui-btn winui-btn-accent";
        }

        body.querySelector("#dlg-imp-zip").addEventListener("click", () => {
          sourcePath = "D:\\Downloads\\Vanilla-1.20.4-Backup.zip";
          srcEl.value = sourcePath;
          nameEl.value = "Vanilla-1.20.4-Backup";
          resetImportWarnings();
        });
        body.querySelector("#dlg-imp-dir").addEventListener("click", () => {
          sourcePath = "D:\\OldServers\\Quilt-SMP";
          srcEl.value = sourcePath;
          nameEl.value = "Quilt-SMP";
          resetImportWarnings();
        });
        srcEl.addEventListener("input", resetImportWarnings);
        nameEl.addEventListener("input", resetImportWarnings);
        body.querySelectorAll('input[name="dlg-imp-mode"]').forEach((r) => {
          r.addEventListener("change", () => {
            if (r.checked) mode = r.value;
            resetImportWarnings();
          });
        });

        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "winui-btn";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", closeModal);
        submitBtn.addEventListener("click", () => {
          const s = srcEl.value.trim();
          const n = nameEl.value.trim();
          errEl.hidden = true;
          if (!s) {
            errEl.textContent = "請先選取來源目錄或 ZIP 壓縮檔";
            errEl.hidden = false;
            return;
          }
          if (!n) {
            errEl.textContent = "請輸入匯入後的伺服器名稱";
            errEl.hidden = false;
            return;
          }
          if (state.servers.some((x) => x.name.toLowerCase() === n.toLowerCase())) {
            errEl.textContent = `伺服器「${n}」已存在，請使用其他名稱`;
            errEl.hidden = false;
            return;
          }
          if (mode === "move" && !moveConfirmed) {
            moveConfirmed = true;
            moveConfirmEl.textContent = `確認遷移匯入：匯入完成後將會移除原始來源「${s}」。若確定繼續，請再次點擊「確認遷移匯入」。`;
            moveConfirmEl.hidden = false;
            submitBtn.textContent = "確認遷移匯入";
            submitBtn.className = "winui-btn winui-btn-danger";
            return;
          }

          const isQuilt = s.toLowerCase().includes("quilt");
          const loader = isQuilt ? "Quilt" : "Vanilla";
          const version = isQuilt ? "1.21.1" : "1.20.4";
          state.servers.push({
            id: n,
            name: n,
            version,
            loader,
            running: false,
            ready: false,
            sizeBytes: 285000000,
            size: "271.8 MB",
            created: nowDateTimeStr(),
            modified: nowDateTimeStr(),
            backupPath: "",
            relPath: n,
            minMem: 1024,
            maxMem: 4096,
            javaMajor: isQuilt ? 21 : 17,
            uptimeSec: 0,
            ramUsage: "-",
            backups: [],
            onlinePlayers: [],
            consoleLogs: [`[系統] 已透過安全匯入流程建立伺服器「${n}」（偵測載入器：${loader}）。`],
            cmdHistory: [],
            properties: DEFAULT_PROPERTIES.map((p) => ({ ...p })),
            usercache: [],
            ops: [],
            whitelist: [],
            bannedPlayers: [],
            bannedIps: []
          });
          if (loader === "Quilt") state.modsByServer[n] = [];
          state.selectedServerId = n;
          closeModal();
          switchPage("manage");
          showInfoBar("匯入完成", `已匯入「${n}」（偵測核心：${loader} ${version}）。`, "success");
        });
        footer.append(document.createElement("span"), Object.assign(document.createElement("div"), { className: "winui-input-row" }));
        footer.lastChild.append(cancelBtn, submitBtn);
      }
    });
  }

  // =====================================================
  // Floating Window 1: ServerMonitorWindow
  // =====================================================
  function openServerMonitorWindow(srv) {
    if (!srv) return;
    let histCursor = -1;

    openModal({
      title: `伺服器主控台監控 — ${srv.name}`,
      size: "is-wide",
      render({ body, footer }) {
        body.innerHTML = `
          <div class="winui-card winui-setting-row">
            <div class="winui-stat-pills">
              <button type="button" class="winui-btn winui-btn-danger" id="mon-kill-btn">強制終止</button>
              <span class="winui-stat-pill" id="mon-ram-pill"></span>
              <span class="winui-stat-pill" id="mon-ver-pill"></span>
              <span class="winui-stat-pill u-accent u-bold" id="mon-player-pill"></span>
              <span class="winui-stat-pill" id="mon-uptime-pill"></span>
            </div>
            <div class="winui-actions-wrap">
              <label class="winui-input-row u-fs-82"><input type="checkbox" id="mon-autoscroll" checked> 自動捲動</label>
              <button type="button" class="winui-btn winui-btn-success" id="mon-start-btn">🚀 啟動</button>
              <button type="button" class="winui-btn winui-btn-danger" id="mon-stop-btn">⏹️ 停止</button>
              <button type="button" class="winui-btn" id="mon-clear-btn">🧹 清除紀錄</button>
              <button type="button" class="winui-btn" id="mon-refresh-btn">🔄 重新整理</button>
            </div>
          </div>
          <div class="winui-monitor-grid u-my0">
            <div class="winui-console-panel u-minh-310">
              <div class="winui-console-bar">
                <span>📜 伺服器終端輸出</span>
                <button type="button" class="winui-btn" id="mon-copy-logs">📋 複製全部紀錄</button>
              </div>
              <div id="mon-logs-box" class="winui-console-logs u-maxh-260"></div>
            </div>
            <div class="winui-card u-flex u-dir-col u-gap-45">
              <div class="u-bold">👥 線上玩家</div>
              <div class="winui-sub-label">點選玩家名稱複製 ID</div>
              <div class="u-flex u-dir-col u-gap-30" id="mon-players-list"></div>
            </div>
          </div>`;

        footer.innerHTML = `
          <form id="mon-cmd-form" class="winui-input-row u-w-full">
            <input id="mon-cmd-input" class="winui-input u-mono" type="text" placeholder="在此輸入指令 (help, list, say Hello, op AlexBuilder, save-all, stop)... 支援 ↑/↓ 歷史指令">
            <button type="submit" class="winui-btn winui-btn-accent" id="mon-cmd-send">傳送指令</button>
          </form>`;

        const killBtn = body.querySelector("#mon-kill-btn");
        const ramPill = body.querySelector("#mon-ram-pill");
        const verPill = body.querySelector("#mon-ver-pill");
        const playerPill = body.querySelector("#mon-player-pill");
        const uptimePill = body.querySelector("#mon-uptime-pill");
        const autoScrollCb = body.querySelector("#mon-autoscroll");
        const startBtn = body.querySelector("#mon-start-btn");
        const stopBtn = body.querySelector("#mon-stop-btn");
        const clearBtn = body.querySelector("#mon-clear-btn");
        const refreshBtn = body.querySelector("#mon-refresh-btn");
        const copyBtn = body.querySelector("#mon-copy-logs");
        const logsBox = body.querySelector("#mon-logs-box");
        const playersList = body.querySelector("#mon-players-list");
        const cmdForm = footer.querySelector("#mon-cmd-form");
        const cmdInput = footer.querySelector("#mon-cmd-input");
        const cmdSend = footer.querySelector("#mon-cmd-send");

        function refreshMonitor() {
          const maxPlayers = srv.properties.find((p) => p.key === "max-players")?.val || "20";
          killBtn.disabled = !srv.running;
          startBtn.disabled = srv.running;
          stopBtn.disabled = !srv.running;
          cmdInput.disabled = !srv.running;
          cmdSend.disabled = !srv.running;
          ramPill.textContent = `RAM: ${srv.ramUsage}`;
          verPill.textContent = srv.version;
          playerPill.textContent = `${srv.onlinePlayers.length} / ${maxPlayers}`;
          uptimePill.textContent = formatDuration(srv.uptimeSec);

          logsBox.innerHTML = "";
          srv.consoleLogs.forEach((line) => {
            const div = document.createElement("div");
            div.textContent = line;
            logsBox.appendChild(div);
          });
          if (autoScrollCb.checked) {
            logsBox.scrollTop = logsBox.scrollHeight;
          }

          playersList.innerHTML = "";
          if (srv.onlinePlayers.length === 0) {
            const empty = document.createElement("div");
            empty.className = "winui-sub-label";
            empty.textContent = "無玩家線上";
            playersList.appendChild(empty);
          } else {
            srv.onlinePlayers.forEach((player) => {
              const pBtn = document.createElement("button");
              pBtn.type = "button";
              pBtn.className = "winui-context-item";
              pBtn.textContent = `● ${player}`;
              pBtn.title = "點選複製玩家名稱";
              pBtn.addEventListener("click", async () => {
                try {
                  await copyPlainText(player);
                } catch {
                  // 忽略瀏覽器剪貼簿權限限制
                }
                srv.consoleLogs.push(`[系統] 已複製玩家名稱「${player}」至剪貼簿`);
                refreshMonitor();
              });
              playersList.appendChild(pBtn);
            });
          }
        }

        state.activeModal.refreshMonitor = refreshMonitor;
        const timerId = setInterval(() => {
          if (srv.running) {
            srv.uptimeSec += 1;
            uptimePill.textContent = formatDuration(srv.uptimeSec);
          }
        }, 1000);
        state.activeModal.onCleanup = () => clearInterval(timerId);

        startBtn.addEventListener("click", () => handleStartOrStopServer(srv, true).then(refreshMonitor));
        stopBtn.addEventListener("click", () => handleStartOrStopServer(srv, false).then(refreshMonitor));
        killBtn.addEventListener("click", () => {
          srv.consoleLogs.push(">>> 強制終止伺服器行程...");
          srv.running = false;
          srv.ready = false;
          srv.uptimeSec = 0;
          srv.ramUsage = "-";
          srv.onlinePlayers = [];
          renderServerTable();
          renderServerDetails();
          refreshMonitor();
          showInfoBar("已強制終止行程", "已釋放 JVM 記憶體並解除執行登錄。", "warn");
        });
        clearBtn.addEventListener("click", () => {
          srv.consoleLogs = [];
          refreshMonitor();
        });
        refreshBtn.addEventListener("click", () => {
          refreshMonitor();
          showInfoBar("已重新整理主控台", "已重新載入日誌緩衝區與行程狀態。", "info");
        });
        copyBtn.addEventListener("click", async () => {
          try {
            await copyPlainText(srv.consoleLogs.join("\n"));
          } catch {
            // 忽略剪貼簿錯誤
          }
          showInfoBar("已複製日誌內容", `共複製 ${srv.consoleLogs.length} 行主控台輸出。`, "success");
        });

        cmdInput.addEventListener("keydown", (e) => {
          if (e.key === "ArrowUp") {
            e.preventDefault();
            if (srv.cmdHistory.length === 0) return;
            histCursor = histCursor < 0 ? srv.cmdHistory.length - 1 : Math.max(0, histCursor - 1);
            cmdInput.value = srv.cmdHistory[histCursor] || "";
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            if (histCursor < 0) return;
            histCursor += 1;
            if (histCursor >= srv.cmdHistory.length) {
              histCursor = -1;
              cmdInput.value = "";
            } else {
              cmdInput.value = srv.cmdHistory[histCursor] || "";
            }
          }
        });

        cmdForm.addEventListener("submit", (e) => {
          e.preventDefault();
          if (!srv.running) return;
          const raw = cmdInput.value.trim();
          if (!raw) return;
          srv.cmdHistory.push(raw);
          histCursor = -1;
          cmdInput.value = "";
          srv.consoleLogs.push(`> ${raw}`);
          const parts = raw.split(/\s+/);
          const cmd = parts[0].toLowerCase();
          if (cmd === "help") {
            srv.consoleLogs.push(`[${nowTimeStr()}] [Server thread/INFO]: 可用模擬指令：help, list, say <訊息>, op <玩家>, save-all, stop`);
          } else if (cmd === "list") {
            const maxP = srv.properties.find((p) => p.key === "max-players")?.val || "20";
            srv.consoleLogs.push(`[${nowTimeStr()}] [Server thread/INFO]: There are ${srv.onlinePlayers.length} of a max of ${maxP} players online: ${srv.onlinePlayers.join(", ")}`);
          } else if (cmd === "say" && parts.length > 1) {
            srv.consoleLogs.push(`[${nowTimeStr()}] [Server thread/INFO]: [Server] ${raw.slice(4)}`);
          } else if (cmd === "save-all") {
            srv.consoleLogs.push(`[${nowTimeStr()}] [Server thread/INFO]: Saved the game`);
          } else if (cmd === "stop") {
            handleStartOrStopServer(srv, false);
          } else {
            srv.consoleLogs.push(`[${nowTimeStr()}] [Server thread/INFO]: 已送出指令至標準輸入：${raw}`);
          }
          refreshMonitor();
        });

        refreshMonitor();
      }
    });
  }

  // =====================================================
  // Floating Window 2: PlayerManagementDialog (4 tabs)
  // =====================================================
  function openPlayerManagementDialog(srv) {
    if (!srv) return;

    const draft = {
      ops: srv.ops.map((x) => ({ ...x })),
      whitelist: srv.whitelist.map((x) => ({ ...x })),
      bannedPlayers: srv.bannedPlayers.map((x) => ({ ...x })),
      bannedIps: srv.bannedIps.map((x) => ({ ...x }))
    };
    let activeTab = "ops";
    let searchTxt = "";

    openModal({
      title: `👥 伺服器名單管理 — ${srv.name}`,
      size: "is-wide",
      render({ body, footer }) {
        body.innerHTML = `
          <div class="winui-players-split u-flex-1">
            <div class="winui-card u-flex u-dir-col u-gap-50">
              <div class="u-bold">曾連線玩家名冊 (usercache)</div>
              <input id="dlg-uc-search" class="winui-input u-flex-none" type="search" placeholder="搜尋玩家名稱...">
              <div class="u-flex u-dir-col u-gap-40 u-scroll-y u-maxh-320" id="dlg-uc-list"></div>
            </div>
            <div class="winui-card u-flex u-dir-col u-gap-65">
              <div class="winui-tab-row u-mb0">
                <button type="button" class="winui-btn winui-btn-accent" data-ptab="ops">👑 管理員名單 (ops.json)</button>
                <button type="button" class="winui-btn" data-ptab="whitelist">📋 白名單 (whitelist.json)</button>
                <button type="button" class="winui-btn" data-ptab="banp">🚫 封鎖玩家 (banned-players)</button>
                <button type="button" class="winui-btn" data-ptab="banip">🌐 封鎖 IP (banned-ips)</button>
              </div>
              <div class="u-flex-1 u-scroll-y" id="dlg-ptab-pane"></div>
            </div>
          </div>`;

        const ucSearch = body.querySelector("#dlg-uc-search");
        const ucList = body.querySelector("#dlg-uc-list");
        const ptabPane = body.querySelector("#dlg-ptab-pane");
        const tabBtns = body.querySelectorAll("[data-ptab]");

        function renderUsercache() {
          const q = searchTxt.trim().toLowerCase();
          const items = srv.usercache.filter((u) => !q || u.name.toLowerCase().includes(q));
          ucList.innerHTML = items.length === 0
            ? `<div class="winui-sub-label">無符合條件的玩家</div>`
            : items
              .map(
                (u) => `<div class="u-p-45 u-border u-r6 u-bg">
                    <div><strong>${escHtml(u.name)}</strong></div>
                    <div class="winui-sub-label u-mono u-fs-72">${escHtml(u.uuid)}</div>
                    <div class="winui-sub-label u-fs-72">到期：${escHtml(u.expires)}</div>
                  </div>`
              )
              .join("");
        }

        function renderTabPane() {
          tabBtns.forEach((b) => {
            const isAct = b.dataset.ptab === activeTab;
            b.className = `winui-btn ${isAct ? "winui-btn-accent" : ""}`;
          });

          if (activeTab === "ops") {
            const knownPlayers = new Map();
            srv.usercache.forEach((u) => knownPlayers.set(u.name, u.uuid));
            draft.ops.forEach((o) => knownPlayers.set(o.name, o.uuid));
            const rows = [...knownPlayers.entries()];

            ptabPane.innerHTML = `
              <div class="winui-sub-label mb-1">權限等級說明：1=繞過重生保護 · 2=使用指令方塊與傳送 · 3=踢出/封鎖玩家 · 4=停止伺服器（最高權限）</div>
              <div class="winui-table-scroll">
                <table class="winui-table">
                  <thead><tr><th>管理員</th><th>玩家名稱</th><th>權限等級</th><th>略過人數限制</th><th>UUID</th></tr></thead>
                  <tbody>
                    ${rows
                .map(([name, uuid]) => {
                  const op = draft.ops.find((o) => o.name === name);
                  return `<tr>
                          <td><input type="checkbox" data-op-toggle="${escHtml(name)}" data-uuid="${escHtml(uuid)}" ${op ? "checked" : ""}></td>
                          <td>${escHtml(name)}</td>
                          <td><select class="winui-select" data-op-level="${escHtml(name)}" ${op ? "" : "disabled"}>
                            ${[1, 2, 3, 4].map((lv) => `<option value="${lv}" ${(op?.level || 4) === lv ? "selected" : ""}>${lv}</option>`).join("")}
                          </select></td>
                          <td><input type="checkbox" data-op-bypass="${escHtml(name)}" ${op?.bypass ? "checked" : ""} ${op ? "" : "disabled"}></td>
                          <td><code>${escHtml(uuid)}</code></td>
                        </tr>`;
                })
                .join("")}
                  </tbody>
                </table>
              </div>`;

            ptabPane.querySelectorAll("[data-op-toggle]").forEach((cb) => {
              cb.addEventListener("change", () => {
                const n = cb.dataset.opToggle;
                const uuid = cb.dataset.uuid;
                if (cb.checked) {
                  if (!draft.ops.some((o) => o.name === n)) {
                    draft.ops.push({ name: n, uuid, level: 4, bypass: false });
                  }
                } else {
                  draft.ops = draft.ops.filter((o) => o.name !== n);
                }
                renderTabPane();
              });
            });
            ptabPane.querySelectorAll("[data-op-level]").forEach((sel) => {
              sel.addEventListener("change", () => {
                const op = draft.ops.find((o) => o.name === sel.dataset.opLevel);
                if (op) op.level = Number.parseInt(sel.value, 10);
              });
            });
            ptabPane.querySelectorAll("[data-op-bypass]").forEach((cb) => {
              cb.addEventListener("change", () => {
                const op = draft.ops.find((o) => o.name === cb.dataset.opBypass);
                if (op) op.bypass = cb.checked;
              });
            });
          } else if (activeTab === "whitelist") {
            const candidates = srv.usercache.filter((u) => !draft.whitelist.some((w) => w.name === u.name));
            ptabPane.innerHTML = `
              <div class="winui-input-row mb-1">
                <select id="dlg-wl-pick" class="winui-select">
                  ${candidates.length ? candidates.map((u) => `<option value="${escHtml(u.name)}">${escHtml(u.name)}</option>`).join("") : `<option value="">(曾連線玩家皆已在白名單)</option>`}
                </select>
                <button type="button" class="winui-btn winui-btn-accent" id="dlg-wl-add" ${candidates.length ? "" : "disabled"}>加入白名單</button>
              </div>
              <div class="winui-table-scroll">
                <table class="winui-table">
                  <thead><tr><th>玩家名稱</th><th>UUID</th><th>移除</th></tr></thead>
                  <tbody>
                    ${draft.whitelist
                .map(
                  (w) => `<tr>
                          <td>${escHtml(w.name)}</td>
                          <td><code>${escHtml(w.uuid)}</code></td>
                          <td><button type="button" class="winui-btn winui-btn-danger" data-wl-rem="${escHtml(w.name)}">移除</button></td>
                        </tr>`
                )
                .join("")}
                  </tbody>
                </table>
              </div>`;

            ptabPane.querySelector("#dlg-wl-add")?.addEventListener("click", () => {
              const picked = ptabPane.querySelector("#dlg-wl-pick")?.value;
              const found = srv.usercache.find((u) => u.name === picked);
              if (found) {
                draft.whitelist.push({ name: found.name, uuid: found.uuid });
                renderTabPane();
              }
            });
            ptabPane.querySelectorAll("[data-wl-rem]").forEach((b) => {
              b.addEventListener("click", () => {
                draft.whitelist = draft.whitelist.filter((w) => w.name !== b.dataset.wlRem);
                renderTabPane();
              });
            });
          } else if (activeTab === "banp") {
            const candidates = srv.usercache.filter((u) => !draft.bannedPlayers.some((b) => b.name === u.name));
            ptabPane.innerHTML = `
              <div class="winui-input-row mb-1">
                <select id="dlg-bp-pick" class="winui-select u-maxw-165">
                  ${candidates.length ? candidates.map((u) => `<option value="${escHtml(u.name)}">${escHtml(u.name)}</option>`).join("") : `<option value="">(無可選玩家)</option>`}
                </select>
                <input id="dlg-bp-reason" class="winui-input" type="text" placeholder="封鎖原因 (選填)">
                <button type="button" class="winui-btn winui-btn-danger" id="dlg-bp-add" ${candidates.length ? "" : "disabled"}>封鎖玩家</button>
              </div>
              <div class="winui-table-scroll">
                <table class="winui-table">
                  <thead><tr><th>玩家名稱</th><th>封鎖原因</th><th>封鎖時間 (GMT+8)</th><th>UUID</th><th>解除封鎖</th></tr></thead>
                  <tbody>
                    ${draft.bannedPlayers
                .map(
                  (b) => `<tr>
                          <td>${escHtml(b.name)}</td><td>${escHtml(b.reason)}</td><td>${escHtml(b.created)}</td>
                          <td><code>${escHtml(b.uuid)}</code></td>
                          <td><button type="button" class="winui-btn" data-bp-unban="${escHtml(b.name)}">解除封鎖</button></td>
                        </tr>`
                )
                .join("")}
                  </tbody>
                </table>
              </div>`;

            ptabPane.querySelector("#dlg-bp-add")?.addEventListener("click", () => {
              const picked = ptabPane.querySelector("#dlg-bp-pick")?.value;
              const found = srv.usercache.find((u) => u.name === picked);
              const reason = ptabPane.querySelector("#dlg-bp-reason")?.value.trim() || "違反伺服器管理規定";
              if (found) {
                draft.bannedPlayers.push({
                  name: found.name,
                  uuid: found.uuid,
                  reason,
                  created: `${nowDateTimeStr()} (GMT+8)`
                });
                renderTabPane();
              }
            });
            ptabPane.querySelectorAll("[data-bp-unban]").forEach((b) => {
              b.addEventListener("click", () => {
                draft.bannedPlayers = draft.bannedPlayers.filter((x) => x.name !== b.dataset.bpUnban);
                renderTabPane();
              });
            });
          } else {
            ptabPane.innerHTML = `
              <div class="winui-sub-label mb-1">支援 IPv4／IPv6 位址封鎖，將寫入 banned-ips.json 並於儲存時套用</div>
              <div class="winui-input-row mb-1">
                <input id="dlg-ip-val" class="winui-input" type="text" placeholder="輸入 IP 位址 (例如 198.51.100.24)">
                <input id="dlg-ip-reason" class="winui-input" type="text" placeholder="封鎖原因 (選填)">
                <button type="button" class="winui-btn winui-btn-danger" id="dlg-ip-add">封鎖 IP</button>
              </div>
              <div class="winui-table-scroll">
                <table class="winui-table">
                  <thead><tr><th>IP 位址</th><th>封鎖原因</th><th>封鎖時間 (GMT+8)</th><th>操作</th></tr></thead>
                  <tbody>
                    ${draft.bannedIps
                .map(
                  (b) => `<tr>
                          <td><code>${escHtml(b.ip)}</code></td><td>${escHtml(b.reason)}</td><td>${escHtml(b.created)}</td>
                          <td><button type="button" class="winui-btn" data-ip-unban="${escHtml(b.ip)}">解除封鎖</button></td>
                        </tr>`
                )
                .join("")}
                  </tbody>
                </table>
              </div>`;

            ptabPane.querySelector("#dlg-ip-add")?.addEventListener("click", () => {
              const ip = ptabPane.querySelector("#dlg-ip-val")?.value.trim() || "";
              const reason = ptabPane.querySelector("#dlg-ip-reason")?.value.trim() || "由管理員封鎖";
              const ipv4Ok = /^(\d{1,3}\.){3}\d{1,3}$/.test(ip) && ip.split(".").every((n) => Number(n) <= 255);
              if (!ipv4Ok && !ip.includes(":")) {
                showInfoBar("IP 格式不正確", "請輸入有效的 IPv4 或 IPv6 位址。", "warn");
                return;
              }
              if (!draft.bannedIps.some((x) => x.ip === ip)) {
                draft.bannedIps.push({ ip, reason, created: `${nowDateTimeStr()} (GMT+8)` });
              }
              renderTabPane();
            });
            ptabPane.querySelectorAll("[data-ip-unban]").forEach((b) => {
              b.addEventListener("click", () => {
                draft.bannedIps = draft.bannedIps.filter((x) => x.ip !== b.dataset.ipUnban);
                renderTabPane();
              });
            });
          }
        }

        tabBtns.forEach((b) => {
          b.addEventListener("click", () => {
            activeTab = b.dataset.ptab;
            renderTabPane();
          });
        });
        ucSearch.addEventListener("input", () => {
          searchTxt = ucSearch.value;
          renderUsercache();
        });

        renderUsercache();
        renderTabPane();

        const status = document.createElement("span");
        status.className = "winui-sub-label";
        status.textContent = "變更將於按下「儲存變更」後原子寫入 JSON 設定檔";
        const right = document.createElement("div");
        right.className = "winui-input-row";
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "winui-btn";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", closeModal);
        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "winui-btn winui-btn-accent";
        saveBtn.textContent = "儲存變更";
        saveBtn.addEventListener("click", () => {
          srv.ops = draft.ops;
          srv.whitelist = draft.whitelist;
          srv.bannedPlayers = draft.bannedPlayers;
          srv.bannedIps = draft.bannedIps;
          closeModal();
          showInfoBar("名單變更已儲存", `已同步更新「${srv.name}」的 ops / whitelist / ban JSON 設定。`, "success");
        });
        right.append(cancelBtn, saveBtn);
        footer.append(status, right);
      }
    });
  }

  // =====================================================
  // Floating Window 3: ServerPropertiesDialog
  // =====================================================
  function openServerPropertiesDialog(srv) {
    if (!srv) return;

    const draftProps = srv.properties.map((p) => ({ ...p }));
    let query = "";
    let category = "全部";

    openModal({
      title: `🔧 編輯伺服器屬性 — ${srv.name} (server.properties)`,
      size: "is-medium",
      render({ body, footer }) {
        body.innerHTML = `
          <div class="winui-input-row">
            <input id="dlg-prop-search" class="winui-input" type="search" placeholder="搜尋屬性鍵名或說明...">
            <select id="dlg-prop-cat" class="winui-select u-maxw-150">
              <option value="全部" selected>全部</option>
              <option value="基本設定">基本設定</option>
              <option value="遊戲設定">遊戲設定</option>
              <option value="世界設定">世界設定</option>
              <option value="網路與安全">網路與安全</option>
              <option value="遠端與進階">遠端與進階</option>
              <option value="自訂屬性">自訂屬性</option>
            </select>
            <button type="button" class="winui-btn" id="dlg-prop-reset-all">全部還原預設值</button>
          </div>
          <div id="dlg-prop-list" class="winui-prop-list"></div>`;

        const searchEl = body.querySelector("#dlg-prop-search");
        const catEl = body.querySelector("#dlg-prop-cat");
        const listEl = body.querySelector("#dlg-prop-list");

        function renderList() {
          const q = query.trim().toLowerCase();
          const items = draftProps.filter((p) => {
            if (category !== "全部" && p.cat !== category) return false;
            if (q && !p.key.toLowerCase().includes(q) && !p.desc.toLowerCase().includes(q)) return false;
            return true;
          });

          listEl.innerHTML = "";
          items.forEach((p) => {
            const row = document.createElement("div");
            row.className = "winui-prop-row";

            const info = document.createElement("div");
            info.innerHTML = `<strong>${escHtml(p.key)}</strong> <span class="winui-pill-tag">${escHtml(p.cat)}</span>
              <div class="winui-sub-label">${escHtml(p.desc)}（預設：<code>${escHtml(p.def)}</code>）</div>`;

            const editorWrap = document.createElement("div");
            if (p.type === "boolean") {
              const lbl = document.createElement("label");
              lbl.className = "winui-input-row";
              const cb = document.createElement("input");
              cb.type = "checkbox";
              cb.checked = p.val === "true";
              cb.addEventListener("change", () => {
                p.val = cb.checked ? "true" : "false";
              });
              lbl.append(cb, document.createTextNode("啟用"));
              editorWrap.appendChild(lbl);
            } else if (p.type === "options") {
              const sel = document.createElement("select");
              sel.className = "winui-select";
              p.options.forEach((optVal) => {
                const opt = document.createElement("option");
                opt.value = optVal;
                opt.textContent = optVal;
                if (p.val === optVal) opt.selected = true;
                sel.appendChild(opt);
              });
              sel.addEventListener("change", () => {
                p.val = sel.value;
              });
              editorWrap.appendChild(sel);
            } else {
              const inp = document.createElement("input");
              inp.className = "winui-input";
              inp.type = "text";
              inp.value = p.val;
              inp.addEventListener("input", () => {
                p.val = inp.value;
              });
              editorWrap.appendChild(inp);
            }

            const resetBtn = document.createElement("button");
            resetBtn.type = "button";
            resetBtn.className = "winui-btn";
            resetBtn.textContent = "預設";
            resetBtn.addEventListener("click", () => {
              p.val = p.def;
              renderList();
            });

            row.append(info, editorWrap, resetBtn);
            listEl.appendChild(row);
          });
        }

        searchEl.addEventListener("input", () => {
          query = searchEl.value;
          renderList();
        });
        catEl.addEventListener("change", () => {
          category = catEl.value;
          renderList();
        });
        body.querySelector("#dlg-prop-reset-all").addEventListener("click", () => {
          draftProps.forEach((p) => {
            p.val = p.def;
          });
          renderList();
          showInfoBar("已全部還原預設", "按下「儲存變更」即可寫回 server.properties。", "info");
        });
        renderList();

        const status = document.createElement("span");
        status.className = "winui-sub-label";
        status.textContent = "修改完成後點「儲存變更」將由 AtomicFileWriter 安全寫回";
        const right = document.createElement("div");
        right.className = "winui-input-row";
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "winui-btn";
        cancelBtn.textContent = "取消";
        cancelBtn.addEventListener("click", closeModal);
        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "winui-btn winui-btn-accent";
        saveBtn.textContent = "儲存變更";
        saveBtn.addEventListener("click", () => {
          const portProp = draftProps.find((p) => p.key === "server-port");
          const portNum = Number(portProp?.val);
          if (!Number.isInteger(portNum) || portNum < 1 || portNum > 65535) {
            showInfoBar("屬性驗證失敗", "server-port 必須是 1 到 65535 的整數。", "warn");
            return;
          }
          srv.properties = draftProps;
          closeModal();
          showInfoBar("已寫入 server.properties", "已透過 AtomicFileWriter 原子取代設定檔。", "success");
        });
        right.append(cancelBtn, saveBtn);
        footer.append(status, right);
      }
    });
  }

  // =====================================================
  // Page 3: ModsView (Local + Online + Modals)
  // =====================================================
  const modsServerSelect = document.getElementById("sim-mods-server");
  const modsTbody = document.getElementById("sim-mods-tbody");
  const modSearchInput = document.getElementById("sim-mod-search");
  const modFilterSelect = document.getElementById("sim-mod-filter");
  const modSelectionHint = document.getElementById("sim-mod-selection-hint");
  const btnCheckUpdate = document.getElementById("sim-mod-check-update");
  const btnSelectAll = document.getElementById("sim-mod-select-all");
  const btnBatchToggle = document.getElementById("sim-mod-batch-toggle");
  const btnDeleteMods = document.getElementById("sim-mod-delete");
  const modTabs = document.querySelectorAll("[data-mod-tab]");
  const modsLocalPane = document.getElementById("sim-mods-local-pane");
  const modsOnlinePane = document.getElementById("sim-mods-online-pane");
  const onlineHintEl = document.getElementById("sim-online-hint");
  const onlineQueryEl = document.getElementById("sim-online-query");
  const onlinePlatformEl = document.getElementById("sim-online-platform");
  const onlineSortEl = document.getElementById("sim-online-sort");
  const onlineSearchBtn = document.getElementById("sim-online-search-btn");
  const onlineTbody = document.getElementById("sim-online-tbody");
  const onlineResultHint = document.getElementById("sim-online-result-hint");
  const onlineQueueHint = document.getElementById("sim-online-queue-hint");
  const btnOpenModPage = document.getElementById("sim-open-mod-page");
  const btnPickVersion = document.getElementById("sim-pick-version-btn");
  const btnViewQueue = document.getElementById("sim-view-queue-btn");
  const btnClearQueue = document.getElementById("sim-clear-queue-btn");
  const btnInstallQueue = document.getElementById("sim-install-queue-btn");

  function getModCapableServers() {
    return state.servers.filter((s) => ["Fabric", "Forge", "NeoForge", "Quilt"].includes(s.loader));
  }

  function syncModServerOptions() {
    if (!modsServerSelect) return;
    const eligible = getModCapableServers();
    const prev = modsServerSelect.value;
    modsServerSelect.innerHTML = "";
    if (eligible.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "目前尚無支援模組的伺服器";
      modsServerSelect.appendChild(opt);
      return;
    }
    eligible.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.name;
      opt.textContent = `${s.name} (${s.version} · ${s.loader})`;
      modsServerSelect.appendChild(opt);
    });
    if (eligible.some((s) => s.name === prev)) {
      modsServerSelect.value = prev;
    }
  }

  function getActiveModServer() {
    const name = modsServerSelect?.value;
    return state.servers.find((s) => s.name === name) || null;
  }

  function getCurrentLocalMods() {
    const srv = getActiveModServer();
    if (!srv) return [];
    if (!state.modsByServer[srv.name]) state.modsByServer[srv.name] = [];
    return state.modsByServer[srv.name];
  }

  function syncModToolbarButtons(filtered) {
    const selectedCount = filtered.filter((m) => m.selected).length;
    if (btnCheckUpdate) btnCheckUpdate.disabled = selectedCount < 1;
    if (btnBatchToggle) btnBatchToggle.disabled = selectedCount < 2;
    if (btnDeleteMods) btnDeleteMods.disabled = selectedCount < 1;
    if (btnSelectAll) {
      btnSelectAll.textContent = filtered.length > 0 && selectedCount === filtered.length ? "取消全選" : "全選";
    }
    if (modSelectionHint) {
      modSelectionHint.textContent =
        selectedCount > 0
          ? `已選取 ${selectedCount} 個模組（Ctrl+點擊可增減選取；≥1 可檢查更新，≥2 可批次切換）`
          : "支援 Ctrl+點擊多選或按「全選」以解鎖批次切換與檢查更新；右鍵列可複製資訊或刪除";
    }
  }

  function renderModsTable() {
    if (!modsTbody) return;
    const all = getCurrentLocalMods();
    const query = (modSearchInput?.value || "").trim().toLowerCase();
    const filterMode = modFilterSelect ? modFilterSelect.value : "全部";

    const filtered = all.filter((m) => {
      if (filterMode === "已啟用" && !m.enabled) return false;
      if (filterMode === "已停用" && m.enabled) return false;
      if (query && !m.name.toLowerCase().includes(query) && !m.fileName.toLowerCase().includes(query)) return false;
      return true;
    });

    const { key, dir } = state.sortState.localMods;
    const mult = dir === "asc" ? 1 : -1;
    filtered.sort((a, b) => naturalCompare(a[key], b[key]) * mult);
    updateSortIndicators("localMods");
    syncModToolbarButtons(filtered);

    modsTbody.innerHTML = "";
    if (filtered.length === 0) {
      modsTbody.innerHTML = `<tr><td colspan="9" class="status-stopped">目前沒有符合篩選條件的本地模組</td></tr>`;
      return;
    }

    filtered.forEach((mod) => {
      const tr = document.createElement("tr");
      tr.setAttribute("aria-selected", mod.selected ? "true" : "false");

      const tdCheck = document.createElement("td");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = mod.enabled;
      cb.setAttribute("aria-label", `啟用 ${mod.name}`);
      cb.addEventListener("click", (e) => e.stopPropagation());
      cb.addEventListener("change", () => {
        mod.enabled = cb.checked;
        mod.fileName = mod.enabled
          ? mod.fileName.replace(/\.jar\.disabled$/i, ".jar")
          : mod.fileName.endsWith(".jar")
            ? `${mod.fileName}.disabled`
            : mod.fileName;
        showInfoBar("切換模組狀態", `${mod.name} 已${mod.enabled ? "啟用" : "停用"}（${mod.fileName}）。`, mod.enabled ? "success" : "info");
        renderModsTable();
      });
      tdCheck.appendChild(cb);
      tr.appendChild(tdCheck);

      const cells = [
        `<strong>${escHtml(mod.name)}</strong>`,
        escHtml(mod.version),
        escHtml(mod.author),
        escHtml(mod.loader),
        escHtml(mod.platform),
        escHtml(mod.size),
        escHtml(mod.modified),
        escHtml(mod.desc)
      ];
      cells.forEach((html, idx) => {
        const td = document.createElement("td");
        td.innerHTML = html;
        if (idx === cells.length - 1) {
          td.className = "winui-td-ellipsis";
          td.title = mod.desc;
        }
        tr.appendChild(td);
      });

      tr.addEventListener("click", (e) => {
        if (e.ctrlKey || e.metaKey) {
          mod.selected = !mod.selected;
        } else {
          all.forEach((x) => {
            x.selected = x === mod;
          });
        }
        renderModsTable();
      });

      tr.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        all.forEach((x) => {
          x.selected = x === mod;
        });
        renderModsTable();
        showContextMenuAt(e.clientX, e.clientY, [
          {
            label: "📋 複製模組資訊",
            onClick: async () => {
              const txt = `模組名稱: ${mod.name}\n版本: ${mod.version}\n狀態: ${mod.enabled ? "啟用" : "停用"}\n載入器: ${mod.loader}`;
              try {
                await copyPlainText(txt);
              } catch {
                // 忽略
              }
              showInfoBar("已複製模組資訊", mod.name, "success");
            }
          },
          {
            label: "📂 在資料夾中顯示",
            onClick: () => showInfoBar("在資料夾中顯示", `${state.serversRoot}\\${getActiveModServer()?.name}\\mods\\${mod.fileName}`, "info")
          },
          {
            label: "🗑️ 刪除模組",
            danger: true,
            onClick: async () => {
              const ok = await showConfirmDialog({
                title: "確認刪除模組",
                message: `確定要刪除「${mod.name}」嗎？`,
                primaryText: "刪除",
                primaryDanger: true
              });
              if (ok) {
                const arr = getCurrentLocalMods();
                const idx = arr.indexOf(mod);
                if (idx >= 0) arr.splice(idx, 1);
                renderModsTable();
                showInfoBar("已刪除模組", mod.name, "info");
              }
            }
          }
        ]);
      });

      modsTbody.appendChild(tr);
    });
  }

  function renderOnlineModsPane() {
    if (!onlineHintEl || !onlineTbody) return;
    const srv = getActiveModServer();
    const platform = onlinePlatformEl ? onlinePlatformEl.value : "Modrinth";
    const isCurseForge = platform === "CurseForge";

    if (isCurseForge) {
      onlineHintEl.textContent = "CurseForge 模組搜尋即將推出，敬請期待";
      if (onlineQueryEl) onlineQueryEl.disabled = true;
      if (onlineSortEl) onlineSortEl.disabled = true;
      if (onlineSearchBtn) onlineSearchBtn.disabled = true;
      if (btnOpenModPage) btnOpenModPage.textContent = "開啟 CurseForge 頁面";
      onlineTbody.innerHTML = `<tr><td colspan="5" class="status-stopped">CurseForge 平台整合正在開發中，請切換回 Modrinth 進行探索。</td></tr>`;
      if (onlineResultHint) onlineResultHint.textContent = "";
      return;
    }

    if (btnOpenModPage) btnOpenModPage.textContent = "開啟 Modrinth 頁面";

    if (onlineQueryEl) onlineQueryEl.disabled = false;
    if (onlineSortEl) onlineSortEl.disabled = false;
    if (onlineSearchBtn) onlineSearchBtn.disabled = false;

    if (!srv) {
      onlineHintEl.textContent = "請先選擇伺服器以篩選相容模組";
    } else {
      onlineHintEl.innerHTML = `✓ 已自動依目標伺服器篩選相容模組：<strong>Minecraft ${escHtml(srv.version)}</strong> ／ <strong>${escHtml(srv.loader)}</strong>（僅從官方 Modrinth CDN 下載並驗證 SHA-512 雜湊）`;
    }

    const q = (onlineQueryEl?.value || "").trim().toLowerCase();
    const sortMode = onlineSortEl ? onlineSortEl.value : "相關性";
    let results = MODRINTH_CATALOG.filter((m) => {
      if (srv && !m.loaders.includes(srv.loader)) return false;
      if (q && !m.name.toLowerCase().includes(q) && !m.desc.toLowerCase().includes(q)) return false;
      return true;
    });
    if (sortMode === "下載量") results.sort((a, b) => b.downloads - a.downloads);
    else if (sortMode === "名稱") results.sort((a, b) => naturalCompare(a.name, b.name));

    onlineTbody.innerHTML = "";
    if (results.length === 0) {
      onlineTbody.innerHTML = `<tr><td colspan="5" class="status-stopped">找不到符合條件的相容模組</td></tr>`;
    } else {
      results.forEach((m) => {
        const tr = document.createElement("tr");
        tr.setAttribute("aria-selected", state.selectedOnlineModId === m.id ? "true" : "false");
        tr.innerHTML = `<td><strong>${escHtml(m.name)}</strong></td><td>${escHtml(m.author)}</td><td>${escHtml(m.dlText)}</td><td><code>${escHtml(m.latest)}</code></td><td>${escHtml(m.desc)}</td>`;
        tr.addEventListener("click", () => {
          state.selectedOnlineModId = m.id;
          renderOnlineModsPane();
        });
        tr.addEventListener("dblclick", () => {
          state.selectedOnlineModId = m.id;
          openModVersionPickerDialog(m);
        });
        onlineTbody.appendChild(tr);
      });
    }

    const localMods = getCurrentLocalMods();
    const installedMatch = results.find((m) => m.id === state.selectedOnlineModId);
    if (onlineResultHint) onlineResultHint.textContent = `搜尋結果：${results.length} 個相容模組（按兩下可挑選版本）`;
    if (onlineQueueHint) onlineQueueHint.textContent = `安裝清單：${state.installQueue.length} 個項目`;
    if (btnOpenModPage) btnOpenModPage.disabled = !installedMatch;
    if (btnPickVersion) btnPickVersion.disabled = !installedMatch;
    if (btnInstallQueue) btnInstallQueue.disabled = state.installQueue.length === 0;
    void localMods;
  }

  function openModVersionPickerDialog(mod) {
    const srv = getActiveModServer();
    if (!mod || !srv) return;
    openModal({
      title: `挑選版本 — ${mod.name}`,
      size: "is-medium",
      render({ body, footer }) {
        body.innerHTML = `
          <p class="winui-sub-label">選擇要安裝的模組版本（已依 ${escHtml(srv.version)} 與 ${escHtml(srv.loader)} 篩選；會自動規劃必要前置相依）</p>
          <div class="winui-table-scroll">
            <table class="winui-table">
              <thead><tr><th>版本號碼</th><th>支援 MC</th><th>載入器</th><th>發布時間</th><th>檔案</th></tr></thead>
              <tbody>
                <tr aria-selected="true"><td><strong>${escHtml(mod.latest)}</strong></td><td>${escHtml(srv.version)}</td><td>${escHtml(srv.loader)}</td><td>2026-11-01</td><td><code>${escHtml(mod.id)}-${escHtml(mod.latest)}.jar</code></td></tr>
              </tbody>
            </table>
          </div>`;

        function enqueueSelected(installNow) {
          const localList = getCurrentLocalMods();
          const added = [];
          if (!state.installQueue.some((q) => q.id === mod.id)) {
            state.installQueue.push({
              action: localList.some((x) => x.id === mod.id) ? "更新" : "安裝",
              id: mod.id,
              name: mod.name,
              author: mod.author,
              version: mod.latest,
              fileName: `${mod.id}-${mod.latest}.jar`,
              reason: "使用者手動挑選"
            });
            added.push(mod.name);
          }
          (mod.deps || []).forEach((depId) => {
            const dep = MODRINTH_CATALOG.find((x) => x.id === depId);
            if (dep && !localList.some((l) => l.id === dep.id) && !state.installQueue.some((q) => q.id === dep.id)) {
              state.installQueue.push({
                action: "安裝",
                id: dep.id,
                name: dep.name,
                author: dep.author,
                version: dep.latest,
                fileName: `${dep.id}-${dep.latest}.jar`,
                reason: `${mod.name} 之必要前置模組`
              });
              added.push(`${dep.name} (前置相依)`);
            }
          });
          closeModal();
          if (installNow) {
            executeInstallQueue();
          } else {
            renderOnlineModsPane();
            showInfoBar("已加入安裝清單", `排入：${added.join("、") || mod.name}`, "info");
          }
        }

        const right = document.createElement("div");
        right.className = "winui-input-row";
        const cBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn", textContent: "取消" });
        cBtn.addEventListener("click", closeModal);
        const qBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn", textContent: "加入安裝清單" });
        qBtn.addEventListener("click", () => enqueueSelected(false));
        const iBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn winui-btn-accent", textContent: "立即安裝" });
        iBtn.addEventListener("click", () => enqueueSelected(true));
        right.append(cBtn, qBtn, iBtn);
        footer.append(document.createElement("span"), right);
      }
    });
  }

  function openInstallQueueDialog() {
    openModal({
      title: "📋 待安裝模組清單",
      size: "is-medium",
      render({ body, footer }) {
        body.innerHTML = state.installQueue.length === 0
          ? `<div class="winui-empty-state">目前安裝佇列為空，請於線上瀏覽點兩下模組挑選版本。</div>`
          : `<div class="winui-table-scroll">
              <table class="winui-table">
                <thead><tr><th>動作</th><th>模組名稱</th><th>版本</th><th>檔案名稱</th><th>原因 / 說明</th></tr></thead>
                <tbody>${state.installQueue
            .map((q) => `<tr><td>${escHtml(q.action)}</td><td>${escHtml(q.name)}</td><td>${escHtml(q.version)}</td><td><code>${escHtml(q.fileName)}</code></td><td>${escHtml(q.reason)}</td></tr>`)
            .join("")}</tbody>
              </table>
            </div>`;

        const clearBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn", textContent: "清空清單" });
        clearBtn.addEventListener("click", () => {
          state.installQueue = [];
          closeModal();
          renderOnlineModsPane();
        });
        const right = document.createElement("div");
        right.className = "winui-input-row";
        const closeBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn", textContent: "關閉" });
        closeBtn.addEventListener("click", closeModal);
        const runBtn = Object.assign(document.createElement("button"), {
          type: "button",
          className: "winui-btn winui-btn-accent",
          textContent: "開始安裝",
          disabled: state.installQueue.length === 0
        });
        runBtn.addEventListener("click", () => {
          closeModal();
          executeInstallQueue();
        });
        right.append(closeBtn, runBtn);
        footer.append(clearBtn, right);
      }
    });
  }

  function executeInstallQueue() {
    const srv = getActiveModServer();
    if (!srv || state.installQueue.length === 0) return;
    const list = getCurrentLocalMods();
    const count = state.installQueue.length;
    state.installQueue.forEach((item) => {
      const existing = list.find((m) => m.id === item.id);
      if (existing) {
        existing.version = item.version;
        existing.latestCompat = item.version;
        existing.fileName = item.fileName;
        existing.modified = nowDateTimeStr();
      } else {
        list.unshift({
          id: item.id,
          name: item.name,
          version: item.version,
          latestCompat: item.version,
          fileName: item.fileName,
          author: item.author,
          loader: srv.loader.toLowerCase(),
          platform: "Modrinth",
          size: "1.1 MB",
          modified: nowDateTimeStr(),
          enabled: true,
          selected: false,
          desc: MODRINTH_CATALOG.find((c) => c.id === item.id)?.desc || "Modrinth 驗證安裝模組"
        });
      }
    });
    state.installQueue = [];
    renderModsTable();
    renderOnlineModsPane();
    showInfoBar("模組安裝完成", `已驗證 SHA-512 並安裝 ${count} 個項目至「${srv.name}」。`, "success");
  }

  function openExportModListDialog() {
    const list = getCurrentLocalMods();
    if (list.length === 0) {
      showInfoBar("無可匯出項目", "目前伺服器沒有本地模組。", "warn");
      return;
    }
    openModal({
      title: "選擇匯出格式",
      render({ body, footer }) {
        body.innerHTML = `
          <p class="winui-sub-label">請選擇欲匯出的模組清單檔案格式：</p>
          <div class="u-flex u-dir-col u-gap-55">
            <label class="winui-input-row"><input type="radio" name="exp-fmt" value="txt" checked> 純文字格式 (*.txt) — 適合快速檢閱與純文字備份</label>
            <label class="winui-input-row"><input type="radio" name="exp-fmt" value="json"> JSON 格式 (*.json) — 包含完整中繼資料與雜湊值</label>
            <label class="winui-input-row"><input type="radio" name="exp-fmt" value="html"> HTML 網頁報表 (*.html) — 具備視覺樣式之獨立表格</label>
            <label class="winui-input-row"><input type="radio" name="exp-fmt" value="xlsx"> Excel 工作表 (*.xlsx) — 使用 OpenXmlSpreadsheetBuilder 記憶體產生</label>
          </div>`;
        const right = document.createElement("div");
        right.className = "winui-input-row";
        const cBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn", textContent: "取消" });
        cBtn.addEventListener("click", closeModal);
        const sBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn winui-btn-accent", textContent: "儲存並匯出" });
        sBtn.addEventListener("click", () => {
          const fmt = body.querySelector('input[name="exp-fmt"]:checked')?.value || "txt";
          closeModal();
          showInfoBar("模組清單已匯出", `已產生 *.${fmt} 報表（共 ${list.length} 個模組；電子試算表自動套用公式注入防護）。`, "success");
        });
        right.append(cBtn, sBtn);
        footer.append(document.createElement("span"), right);
      }
    });
  }

  function openModUpdatesDialog() {
    const selected = getCurrentLocalMods().filter((m) => m.selected);
    const candidates = selected.filter((m) => m.latestCompat && m.latestCompat !== m.version).map((m) => ({ mod: m, checked: true }));
    if (candidates.length === 0) {
      showInfoBar("檢查模組更新完成", `已透過 FlexVersion 與 Modrinth API 比對 ${selected.length} 個已選模組，皆為最新相容版本。`, "success");
      return;
    }
    openModal({
      title: "📦 發現可用模組更新",
      size: "is-medium",
      render({ body, footer }) {
        body.innerHTML = `
          <p class="winui-sub-label">下列模組在線上平台上有相容的新版本：</p>
          <div class="winui-table-scroll">
            <table class="winui-table">
              <thead><tr><th>更新</th><th>模組名稱</th><th>目前版本</th><th>最新版本</th><th>來源平台</th><th>新檔案名稱</th></tr></thead>
              <tbody id="dlg-upd-tbody"></tbody>
            </table>
          </div>`;
        const tbody = body.querySelector("#dlg-upd-tbody");
        candidates.forEach((c) => {
          const tr = document.createElement("tr");
          const newFile = `${c.mod.id}-${c.mod.latestCompat}.jar`;
          tr.innerHTML = `<td><input type="checkbox" checked></td><td>${escHtml(c.mod.name)}</td><td>${escHtml(c.mod.version)}</td><td class="status-running">${escHtml(c.mod.latestCompat)}</td><td>${escHtml(c.mod.platform)}</td><td><code>${escHtml(newFile)}</code></td>`;
          tr.querySelector("input").addEventListener("change", (e) => {
            c.checked = e.target.checked;
          });
          tbody.appendChild(tr);
        });

        const right = document.createElement("div");
        right.className = "winui-input-row";
        const cBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn", textContent: "關閉" });
        cBtn.addEventListener("click", closeModal);
        const uBtn = Object.assign(document.createElement("button"), { type: "button", className: "winui-btn winui-btn-accent", textContent: "立即更新所選模組" });
        uBtn.addEventListener("click", () => {
          let count = 0;
          candidates.forEach((c) => {
            if (c.checked) {
              c.mod.version = c.mod.latestCompat;
              c.mod.fileName = `${c.mod.id}-${c.mod.latestCompat}.jar`;
              c.mod.modified = nowDateTimeStr();
              count++;
            }
          });
          closeModal();
          renderModsTable();
          showInfoBar("模組更新完成", `已安全下載與更換 ${count} 個模組。`, "success");
        });
        right.append(cBtn, uBtn);
        footer.append(document.createElement("span"), right);
      }
    });
  }

  if (modsServerSelect) {
    modsServerSelect.addEventListener("change", () => {
      state.selectedOnlineModId = null;
      renderModsTable();
      renderOnlineModsPane();
    });
  }
  if (modSearchInput) modSearchInput.addEventListener("input", renderModsTable);
  if (modFilterSelect) modFilterSelect.addEventListener("change", renderModsTable);
  if (onlinePlatformEl) onlinePlatformEl.addEventListener("change", renderOnlineModsPane);
  if (onlineSortEl) onlineSortEl.addEventListener("change", renderOnlineModsPane);
  if (onlineSearchBtn) onlineSearchBtn.addEventListener("click", renderOnlineModsPane);
  if (onlineQueryEl) onlineQueryEl.addEventListener("input", renderOnlineModsPane);
  if (btnPickVersion) {
    btnPickVersion.addEventListener("click", () => {
      const mod = MODRINTH_CATALOG.find((m) => m.id === state.selectedOnlineModId);
      if (mod) openModVersionPickerDialog(mod);
    });
  }
  if (btnViewQueue) btnViewQueue.addEventListener("click", openInstallQueueDialog);
  if (btnClearQueue) {
    btnClearQueue.addEventListener("click", () => {
      state.installQueue = [];
      renderOnlineModsPane();
      showInfoBar("已清空安裝清單", "待安裝佇列已清除。", "info");
    });
  }
  if (btnInstallQueue) btnInstallQueue.addEventListener("click", executeInstallQueue);
  if (btnOpenModPage) {
    btnOpenModPage.addEventListener("click", () => {
      const mod = MODRINTH_CATALOG.find((m) => m.id === state.selectedOnlineModId);
      if (mod) showInfoBar("前往外部專案頁", `https://modrinth.com/mod/${mod.id}`, "info");
    });
  }

  modTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const isLocal = tab.dataset.modTab === "local";
      modTabs.forEach((t) => {
        t.className = `winui-btn ${t === tab ? "winui-btn-accent" : ""}`;
        t.setAttribute("aria-pressed", String(t === tab));
      });
      if (modsLocalPane) modsLocalPane.hidden = !isLocal;
      if (modsOnlinePane) modsOnlinePane.hidden = isLocal;
      if (!isLocal) renderOnlineModsPane();
    });
  });

  // =====================================================
  // Page 4: AboutPreferencesView
  // =====================================================
  const simThemeSelect = document.getElementById("sim-internal-theme");
  const accentPicker = document.getElementById("sim-accent-picker");
  const accentLabel = document.getElementById("sim-accent-label");
  const resetAccentBtn = document.getElementById("sim-reset-accent-btn");
  const autoUpdateCb = document.getElementById("sim-pref-autoupdate");
  const checkUpdateBtn = document.getElementById("sim-check-update-btn");
  const autoBackupCb = document.getElementById("sim-pref-autobackup");
  const retentionInput = document.getElementById("sim-pref-retention");

  function isLightAccentHex(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex);
    if (!m) return false;
    const n = parseInt(m[1], 16);
    const channels = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    const luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    return luminance > 0.36;
  }

  function applySimAccent(hex, isCustom = true) {
    state.prefs.accent = hex;
    state.prefs.isCustomAccent = isCustom;
    if (isCustom) {
      app.style.setProperty("--w-accent", hex);
      app.style.setProperty("--w-on-accent", isLightAccentHex(hex) ? "#001b33" : "#ffffff");
    } else {
      app.style.removeProperty("--w-accent");
      app.style.removeProperty("--w-on-accent");
    }
    if (accentPicker) accentPicker.value = hex.toLowerCase();
    if (accentLabel) {
      accentLabel.textContent = isCustom
        ? `目前自訂顏色：${hex.toUpperCase()}`
        : "使用 Windows 系統強調色（預設）";
    }
    if (resetAccentBtn) {
      resetAccentBtn.disabled = !isCustom;
    }
  }

  function applySimTheme(mode) {
    state.prefs.theme = mode;
    app.setAttribute("data-winui-theme", mode);
    if (simThemeSelect) simThemeSelect.value = mode;
  }

  if (simThemeSelect) {
    simThemeSelect.addEventListener("change", () => {
      applySimTheme(simThemeSelect.value);
      showInfoBar("已切換主題模式", `視窗外觀已套用「${simThemeSelect.selectedOptions[0]?.textContent}」。`, "info");
    });
  }
  if (accentPicker) {
    accentPicker.addEventListener("input", () => {
      applySimAccent(accentPicker.value, true);
    });
  }
  if (autoUpdateCb && checkUpdateBtn) {
    autoUpdateCb.addEventListener("change", () => {
      state.prefs.autoUpdate = autoUpdateCb.checked;
      // 真實 XAML InverseBoolToVisibilityConverter：關閉自動檢查更新時才顯示手動按鈕
      checkUpdateBtn.hidden = state.prefs.autoUpdate;
    });
    checkUpdateBtn.addEventListener("click", () => {
      showInfoBar("檢查更新完成", `目前已是最新版本 (${document.querySelector(".brand-version").textContent})。`, "info");
    });
  }
  if (autoBackupCb) {
    autoBackupCb.addEventListener("change", () => {
      state.prefs.autoBackupBeforeStart = autoBackupCb.checked;
    });
  }
  if (retentionInput) {
    retentionInput.addEventListener("change", () => {
      const val = Number.parseInt(retentionInput.value, 10);
      const clamped = Number.isNaN(val) ? 10 : Math.min(100, Math.max(1, val));
      retentionInput.value = String(clamped);
      state.prefs.retention = clamped;
    });
  }

  // =====================================================
  // Global Navigation, Sort, Modal & Action Wiring
  // =====================================================
  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.simNav) switchPage(btn.dataset.simNav);
    });
  });
  quickModalBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const srv = ensureSelectedServerForModal();
      if (!srv) {
        showInfoBar("沒有可用伺服器", "請先於建立伺服器頁面新增一台伺服器。", "warn");
        return;
      }
      const m = btn.dataset.simOpenModal;
      if (m === "monitor") openServerMonitorWindow(srv);
      else if (m === "players") openPlayerManagementDialog(srv);
      else if (m === "properties") openServerPropertiesDialog(srv);
    });
  });

  if (toggleRunBtn) {
    toggleRunBtn.addEventListener("click", () => {
      const srv = getSelectedServer();
      if (srv) handleStartOrStopServer(srv, !srv.running);
    });
  }

  document.querySelectorAll("[data-sort-table]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tbl = btn.dataset.sortTable;
      const key = btn.dataset.sortKey;
      const cur = state.sortState[tbl];
      if (!cur) return;
      if (cur.key === key) cur.dir = cur.dir === "asc" ? "desc" : "asc";
      else {
        cur.key = key;
        cur.dir = "asc";
      }
      if (tbl === "servers") renderServerTable();
      else if (tbl === "localMods") renderModsTable();
    });
  });

  // 右鍵選單開啟時的 Esc 由 popover 原生處理，其餘才關閉模擬視窗
  app.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.activeModal && !state.activeModal.locked && !contextMenu.matches(":popover-open")) {
      e.preventDefault();
      closeModal();
    }
  });

  document.querySelectorAll("[data-sim-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.simAction;
      const srv = getSelectedServer();

      switch (action) {
        case "open-import-dialog":
          openImportServerDialog();
          break;
        case "open-java-dialog":
          openManageJavaDialog();
          break;
        case "open-jvm-dialog":
          openJvmArgsDialog();
          break;
        case "folder-toast":
          showInfoBar("開啟伺服器主目錄", `目標路徑：${state.serversRoot}`, "info");
          break;
        case "open-server-folder":
          if (srv) showInfoBar("開啟資料夾", `目標路徑：${state.serversRoot}\\${srv.relPath}`, "info");
          break;
        case "detect-toast":
          if (manageStatusEl) manageStatusEl.textContent = `掃描完成：共偵測 ${state.servers.length} 台有效伺服器`;
          showInfoBar("偵測現有伺服器", `已於 ${state.serversRoot} 掃描並驗證 ${state.servers.length} 台伺服器核心檔案。`, "success");
          break;
        case "refresh-toast":
          renderServerTable();
          renderServerDetails();
          showInfoBar("已重新整理", "已同步更新伺服器清單與目錄大小。", "info");
          break;
        case "change-root": {
          if (state.servers.some((s) => s.running)) {
            showInfoBar("無法修改路徑", "目前有伺服器正在執行中，請先停止伺服器後再修改存放路徑。", "warn");
            return;
          }
          const nextRoot = state.serversRoot === "C:\\Minecraft\\servers" ? "D:\\Games\\Minecraft\\servers" : "C:\\Minecraft\\servers";
          const decision = await showConfirmDialog({
            title: "是否遷移伺服器資料",
            message: `偵測到原路徑已有存放伺服器：\n${state.serversRoot}\n\n是否要將存放資料遷移至新路徑？\n${nextRoot}\n\n• 是，遷移資料：將所有資料搬移至空資料夾\n• 否，僅改設定：保留原處資料，直接更新路徑設定`,
            primaryText: "是，遷移資料",
            secondaryText: "否，僅改設定",
            closeText: "取消"
          });
          if (decision === null) return;
          state.serversRoot = nextRoot;
          renderServerTable();
          renderServerDetails();
          showInfoBar(
            decision ? "已遷移並更新存放路徑" : "已僅更新存放路徑設定",
            `伺服器偵測路徑已改為 ${nextRoot}（真實程式將自動重新啟動套用）。`,
            "success"
          );
          break;
        }
        case "open-monitor":
          if (srv) openServerMonitorWindow(srv);
          break;
        case "open-properties":
          if (srv) openServerPropertiesDialog(srv);
          break;
        case "open-players":
          if (srv) openPlayerManagementDialog(srv);
          break;
        case "backup-now":
          handleBackupServer(srv);
          break;
        case "open-restore":
          openRestoreBackupDialog(srv);
          break;
        case "delete-server":
          if (!srv) return;
          if (srv.running) {
            showInfoBar("無法刪除", `伺服器「${srv.name}」正在執行中，請先停止後再刪除。`, "warn");
            return;
          }
          {
            const backupCount = srv.backups.length;
            const decision = backupCount > 0
              ? await showConfirmDialog({
                title: "確認刪除伺服器",
                message: `確定要刪除伺服器「${srv.name}」嗎？\n\n⚠️ 這將永久刪除伺服器檔案，無法復原！\n\n偵測到此伺服器有 ${backupCount} 個外部備份檔案，是否一併刪除？`,
                primaryText: "連同備份一併刪除",
                primaryDanger: true,
                secondaryText: "僅刪除伺服器",
                closeText: "取消"
              })
              : await showConfirmDialog({
                title: "確認刪除伺服器",
                message: `確定要刪除伺服器「${srv.name}」嗎？\n\n⚠️ 這將永久刪除伺服器檔案，無法復原！`,
                primaryText: "確定刪除",
                primaryDanger: true
              });
            if (decision === null) return;
            if (decision === false && backupCount === 0) return;
            state.servers = state.servers.filter((s) => s.id !== srv.id);
            state.selectedServerId = null;
            renderServerTable();
            renderServerDetails();
            const desc = decision === true && backupCount > 0
              ? `已刪除「${srv.name}」並移除 ${backupCount} 份外部備份。`
              : `已刪除伺服器「${srv.name}」。`;
            showInfoBar("已刪除伺服器", desc, "info");
          }
          break;
        case "refresh-mod-servers":
          syncModServerOptions();
          renderModsTable();
          showInfoBar("伺服器清單已更新", "僅列出 Fabric、Quilt、Forge 與 NeoForge 伺服器。", "info");
          break;
        case "mod-import": {
          const targetSrv = getActiveModServer();
          if (!targetSrv) return;
          const mods = getCurrentLocalMods();
          const sampleId = "architectury";
          if (!mods.some((m) => m.id === sampleId)) {
            mods.unshift({
              id: sampleId,
              name: "Architectury API",
              version: "13.0.8",
              latestCompat: "13.0.8",
              fileName: "architectury-13.0.8-fabric.jar",
              author: "shedaniel",
              loader: targetSrv.loader.toLowerCase(),
              platform: "Local",
              size: "590 KB",
              modified: nowDateTimeStr(),
              enabled: true,
              selected: false,
              desc: "由本機 .jar 檔匯入的跨平台模組相依函式庫"
            });
          }
          renderModsTable();
          showInfoBar("匯入模組完成", `已複製 .jar 至「${targetSrv.name}」mods 資料夾並完成掃描。`, "success");
          break;
        }
        case "mod-refresh":
          renderModsTable();
          showInfoBar("已重新整理模組清單", "已依據檔案大小與修改時間更新快取索引。", "info");
          break;
        case "mod-select-all": {
          const mods = getCurrentLocalMods();
          const allSelected = mods.length > 0 && mods.every((m) => m.selected);
          mods.forEach((m) => {
            m.selected = !allSelected;
          });
          renderModsTable();
          break;
        }
        case "mod-batch-toggle": {
          const targets = getCurrentLocalMods().filter((m) => m.selected);
          if (targets.length < 2) {
            showInfoBar("選取數量不足", "批次切換功能需選取至少 2 個模組。", "warn");
            return;
          }
          targets.forEach((m) => {
            m.enabled = !m.enabled;
            m.fileName = m.enabled
              ? m.fileName.replace(/\.jar\.disabled$/i, ".jar")
              : `${m.fileName}.disabled`;
          });
          renderModsTable();
          showInfoBar("批次切換完成", `已反轉 ${targets.length} 個選取模組的啟用狀態。`, "success");
          break;
        }
        case "mod-open-folder":
          showInfoBar("開啟模組資料夾", `${state.serversRoot}\\${getActiveModServer()?.name || ""}\\mods`, "info");
          break;
        case "mod-delete": {
          const mods = getCurrentLocalMods();
          const targets = mods.filter((m) => m.selected);
          if (targets.length === 0) return;
          const ok = await showConfirmDialog({
            title: "確認刪除選取模組",
            message: `確定要從伺服器中移除選取的 ${targets.length} 個模組檔案嗎？`,
            primaryText: "刪除",
            primaryDanger: true
          });
          if (ok) {
            const targetSrv = getActiveModServer();
            if (targetSrv) {
              state.modsByServer[targetSrv.name] = mods.filter((m) => !m.selected);
            }
            renderModsTable();
            showInfoBar("已刪除選取模組", `共移除 ${targets.length} 個模組檔案。`, "info");
          }
          break;
        }
        case "mod-check-update":
          openModUpdatesDialog();
          break;
        case "mod-export":
          openExportModListDialog();
          break;
        case "reset-window-size":
          showInfoBar("已重設視窗大小", "主視窗尺寸已恢復為預設 1350 × 820（置中顯示）。", "info");
          break;
        case "reset-accent-color":
          applySimAccent("#005FB8", false);
          showInfoBar("已重設為系統強調色", "色彩覆蓋已清除並恢復系統預設值。", "info");
          break;
        case "restore-all-defaults": {
          const ok = await showConfirmDialog({
            title: "還原所有設定",
            message: "確定要將主題、強調色、自動更新與備份數量重設回出廠預設值嗎？",
            primaryText: "還原預設",
            primaryDanger: true
          });
          if (!ok) return;
          applySimTheme("system");
          applySimAccent("#005FB8", false);
          state.prefs.autoUpdate = true;
          state.prefs.autoBackupBeforeStart = false;
          state.prefs.retention = 10;
          if (autoUpdateCb) autoUpdateCb.checked = true;
          if (checkUpdateBtn) checkUpdateBtn.hidden = true;
          if (autoBackupCb) autoBackupCb.checked = false;
          if (retentionInput) retentionInput.value = "10";
          showInfoBar("設定已還原", "所有偏好設定已恢復為預設值。", "success");
          break;
        }
        default:
          break;
      }
    });
  });

  // 初始化為真實啟動頁面「建立伺服器」與預設系統主題
  applySimTheme("system");
  applySimAccent("#005FB8", false);
  syncCreateFormState();
  switchPage("create");
}
