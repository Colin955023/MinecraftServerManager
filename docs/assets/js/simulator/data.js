export const MC_JAVA_MAP = {
  "1.21.4": 21,
  "1.21.1": 21,
  "1.20.4": 17,
  "1.19.4": 17
};

export const LOADER_VERSIONS = {
  Paper: ["最新穩定版 (Paper)"],
  Fabric: ["0.16.10", "0.16.9"],
  Quilt: ["0.27.1", "0.26.4"],
  Forge: ["54.1.0", "54.0.26", "49.1.13", "45.3.0"],
  NeoForge: ["21.4.112-beta", "21.1.121", "20.4.237"]
};

export const DANGEROUS_JVM_PREFIXES = [
  "-XX:OnError",
  "-XX:OnOutOfMemoryError",
  "-agentpath",
  "-agentlib",
  "-Xbootclasspath"
];

export const JVM_PRESETS_ZGC = [
  { opt: "-XX:+UseZGC", desc: "啟用低延遲 ZGC 垃圾回收器（Java 21+ 建議）" },
  { opt: "-XX:+ZGenerational", desc: "啟用世代化 ZGC 以降低停頓時間" },
  { opt: "-XX:+AlwaysPreTouch", desc: "啟動時預先配置記憶體分頁，減少執行期抖動" }
];

export const JVM_PRESETS_G1 = [
  { opt: "-XX:+UseG1GC", desc: "啟用 G1GC 收集器（Java 8～17 建議）" },
  { opt: "-XX:+ParallelRefProcEnabled", desc: "平行處理物件參考，縮短停頓時間" },
  { opt: "-XX:MaxGCPauseMillis=200", desc: "設定單次 GC 最大停頓目標（200 ms）" },
  { opt: "-XX:+AlwaysPreTouch", desc: "啟動時預先分派堆積記憶體分頁" }
];

export const MODRINTH_CATALOG = [
  {
    id: "fabric-api",
    name: "Fabric API",
    author: "modmuss50",
    downloads: 95400000,
    dlText: "95.4M",
    latest: "0.115.1+1.21.1",
    loaders: ["Fabric", "Quilt"],
    mc: "1.21.1",
    desc: "大多數 Fabric 模組運作所需的官方核心 API 函式庫",
    deps: []
  },
  {
    id: "sodium",
    name: "Sodium",
    author: "jellysquid3",
    downloads: 48200000,
    dlText: "48.2M",
    latest: "mc1.21.1-0.6.5",
    loaders: ["Fabric", "Quilt", "NeoForge"],
    mc: "1.21.1",
    desc: "現代化引擎效能最佳化與幀率提升模組",
    deps: ["fabric-api"]
  },
  {
    id: "lithium",
    name: "Lithium",
    author: "jellysquid3",
    downloads: 31700000,
    dlText: "31.7M",
    latest: "mc1.21.1-0.13.1",
    loaders: ["Fabric", "Quilt", "NeoForge"],
    mc: "1.21.1",
    desc: "不影響原版遊戲邏輯的伺服器物理與 AI 效能最佳化",
    deps: []
  },
  {
    id: "cloth-config",
    name: "Cloth Config API",
    author: "shedaniel",
    downloads: 42500000,
    dlText: "42.5M",
    latest: "15.0.140+fabric",
    loaders: ["Fabric", "Quilt", "Forge", "NeoForge"],
    mc: "1.21.1",
    desc: "眾多模組共用的設定介面相依函式庫",
    deps: []
  },
  {
    id: "ferrite-core",
    name: "FerriteCore",
    author: "malte0811",
    downloads: 38900000,
    dlText: "38.9M",
    latest: "7.0.2",
    loaders: ["Fabric", "Quilt", "Forge", "NeoForge"],
    mc: "1.21.1",
    desc: "大幅減少伺服器與用戶端方塊狀態記憶體佔用",
    deps: ["cloth-config"]
  }
];

export const DEFAULT_PROPERTIES = [
  { key: "server-port", cat: "基本設定", type: "text", def: "25565", val: "25565", desc: "伺服器監聽的 TCP 連接埠 (1–65535)" },
  { key: "motd", cat: "基本設定", type: "text", def: "A Minecraft Server", val: "Survival Paper 1.21.4 Community", desc: "多人遊戲伺服器列表顯示的歡迎標語" },
  { key: "max-players", cat: "基本設定", type: "text", def: "20", val: "20", desc: "同時可連線的最大玩家人數" },
  { key: "gamemode", cat: "遊戲設定", type: "options", options: ["survival", "creative", "adventure", "spectator"], def: "survival", val: "survival", desc: "新加入玩家的預設遊戲模式" },
  { key: "difficulty", cat: "遊戲設定", type: "options", options: ["peaceful", "easy", "normal", "hard"], def: "easy", val: "hard", desc: "遊戲難度等級" },
  { key: "pvp", cat: "遊戲設定", type: "boolean", def: "true", val: "true", desc: "是否允許玩家之間互相攻擊" },
  { key: "level-name", cat: "世界設定", type: "text", def: "world", val: "world", desc: "主世界存檔資料夾名稱" },
  { key: "view-distance", cat: "世界設定", type: "text", def: "10", val: "12", desc: "伺服器傳送給玩家的視距區塊半徑 (3–32)" },
  { key: "allow-flight", cat: "世界設定", type: "boolean", def: "false", val: "false", desc: "是否允許玩家在生存模式使用飛行外掛／模組" },
  { key: "white-list", cat: "網路與安全", type: "boolean", def: "false", val: "true", desc: "啟用後僅允許白名單玩家連線" },
  { key: "online-mode", cat: "網路與安全", type: "boolean", def: "true", val: "true", desc: "向 Mojang 驗證正版玩家帳號" },
  { key: "enable-rcon", cat: "遠端與進階", type: "boolean", def: "false", val: "false", desc: "是否啟用 RCON 遠端主控台協定" },
  { key: "simulation-distance", cat: "遠端與進階", type: "text", def: "10", val: "10", desc: "實體與紅石模擬更新的區塊半徑" },
  { key: "sync-chunk-writes", cat: "自訂屬性", type: "boolean", def: "true", val: "true", desc: "同步寫入區塊資料以降低當機損毀風險" }
];

export const SYSTEM_MEMORY_MB = 16384;

export function createInitialState() {
  return {
    activePage: "create",
    activeModal: null,
    serversRoot: "C:\\Minecraft\\servers",
    selectedServerId: null,
    createNameManuallyEdited: false,
    customJvmArgs: null,
    installedJavas: [
      { major: 21, vendor: "Eclipse Adoptium", path: "C:\\Program Files\\Eclipse Adoptium\\jdk-21.0.6\\bin\\java.exe" },
      { major: 17, vendor: "Microsoft Build of OpenJDK", path: "C:\\Program Files\\Microsoft\\jdk-17.0.14\\bin\\java.exe" }
    ],
    sortState: {
      servers: { key: "name", dir: "asc" },
      localMods: { key: "name", dir: "asc" }
    },
    prefs: {
      autoUpdate: true,
      theme: "system",
      accent: "#005FB8",
      isCustomAccent: false,
      autoBackupBeforeStart: false,
      retention: 10
    },
    servers: [
      {
        id: "Survival-Paper",
        name: "Survival-Paper",
        version: "1.21.4",
        loader: "Paper",
        running: true,
        ready: true,
        sizeBytes: 342000000,
        size: "326.1 MB",
        created: "2025-10-08 19:20",
        modified: "2026-11-14 12:30",
        backupPath: "D:\\MC-Backups\\Survival-Paper",
        relPath: "Survival-Paper",
        minMem: 1024,
        maxMem: 4096,
        javaMajor: 21,
        uptimeSec: 6138,
        ramUsage: "2,418 MB",
        backups: [
          { fileName: "Survival-Paper_20261114_1100.zip", size: "184.2 MB", created: "2026-11-14 11:00" },
          { fileName: "Survival-Paper_20261113_2200.zip", size: "182.9 MB", created: "2026-11-13 22:00" },
          { fileName: "Survival-Paper_20261112_2200.zip", size: "180.4 MB", created: "2026-11-12 22:00" }
        ],
        onlinePlayers: ["Colin_TW", "AlexBuilder"],
        consoleLogs: [
          "[10:50:12] [Server thread/INFO]: Starting minecraft server version 1.21.4 (Paper Build #212)",
          "[10:50:14] [Server thread/INFO]: Preparing level \"world\"",
          "[10:50:16] [Server thread/INFO]: Done (2.814s)! For help, type \"help\"",
          "[11:04:19] [Server thread/INFO]: Colin_TW joined the game",
          "[11:18:45] [Server thread/INFO]: AlexBuilder joined the game"
        ],
        cmdHistory: ["list", "save-all"],
        properties: DEFAULT_PROPERTIES.map((p) => ({ ...p })),
        usercache: [
          { name: "Colin_TW", uuid: "c9f1a4b2-3e88-49e2-91a0-8f0123abcd01", expires: "2026-12-14 19:00 (GMT+8)" },
          { name: "AlexBuilder", uuid: "a204d911-7b3c-4f21-83b1-5c9812efaa12", expires: "2026-12-12 21:15 (GMT+8)" },
          { name: "SteveRedstone", uuid: "f88c210e-4412-40d9-b008-19bc77de4409", expires: "2026-12-03 14:40 (GMT+8)" }
        ],
        ops: [
          { name: "Colin_TW", uuid: "c9f1a4b2-3e88-49e2-91a0-8f0123abcd01", level: 4, bypass: true }
        ],
        whitelist: [
          { name: "Colin_TW", uuid: "c9f1a4b2-3e88-49e2-91a0-8f0123abcd01" },
          { name: "AlexBuilder", uuid: "a204d911-7b3c-4f21-83b1-5c9812efaa12" }
        ],
        bannedPlayers: [
          { name: "GrieferX99", uuid: "d10077ac-9831-42f0-991a-001122334455", reason: "惡意破壞公有建築", created: "2026-10-20 22:18 (GMT+8)" }
        ],
        bannedIps: [
          { ip: "203.0.113.45", reason: "頻繁發送異常連線封包", created: "2026-10-21 09:05 (GMT+8)" }
        ]
      },
      {
        id: "Modded-Fabric",
        name: "Modded-Fabric",
        version: "1.21.1",
        loader: "Fabric",
        running: false,
        ready: false,
        sizeBytes: 626000000,
        size: "597.4 MB",
        created: "2026-01-15 16:40",
        modified: "2026-11-13 21:15",
        backupPath: "D:\\MC-Backups\\Modded-Fabric",
        relPath: "Modded-Fabric",
        minMem: 2048,
        maxMem: 6144,
        javaMajor: 21,
        uptimeSec: 0,
        ramUsage: "-",
        backups: [
          { fileName: "Modded-Fabric_20261113_2100.zip", size: "310.5 MB", created: "2026-11-13 21:00" }
        ],
        onlinePlayers: [],
        consoleLogs: ["[系統] 伺服器目前未執行。按下上方「啟動」以啟動伺服器。"],
        cmdHistory: [],
        properties: DEFAULT_PROPERTIES.map((p) =>
          p.key === "server-port" ? { ...p, val: "25566" } : p.key === "motd" ? { ...p, val: "Fabric 1.21.1 Modded World" } : { ...p }
        ),
        usercache: [
          { name: "Colin_TW", uuid: "c9f1a4b2-3e88-49e2-91a0-8f0123abcd01", expires: "2026-12-10 20:00 (GMT+8)" },
          { name: "SteveRedstone", uuid: "f88c210e-4412-40d9-b008-19bc77de4409", expires: "2026-12-01 12:30 (GMT+8)" }
        ],
        ops: [{ name: "Colin_TW", uuid: "c9f1a4b2-3e88-49e2-91a0-8f0123abcd01", level: 4, bypass: false }],
        whitelist: [{ name: "Colin_TW", uuid: "c9f1a4b2-3e88-49e2-91a0-8f0123abcd01" }],
        bannedPlayers: [],
        bannedIps: []
      },
      {
        id: "Tech-NeoForge",
        name: "Tech-NeoForge",
        version: "1.21.1",
        loader: "NeoForge",
        running: false,
        ready: false,
        sizeBytes: 1210000000,
        size: "1.13 GB",
        created: "2026-04-02 10:12",
        modified: "2026-11-10 18:05",
        backupPath: "",
        relPath: "Tech-NeoForge",
        minMem: 2048,
        maxMem: 8192,
        javaMajor: 21,
        uptimeSec: 0,
        ramUsage: "-",
        backups: [],
        onlinePlayers: [],
        consoleLogs: ["[系統] 伺服器目前未執行。"],
        cmdHistory: [],
        properties: DEFAULT_PROPERTIES.map((p) =>
          p.key === "server-port" ? { ...p, val: "25567" } : { ...p }
        ),
        usercache: [
          { name: "AlexBuilder", uuid: "a204d911-7b3c-4f21-83b1-5c9812efaa12", expires: "2026-12-09 18:05 (GMT+8)" }
        ],
        ops: [],
        whitelist: [],
        bannedPlayers: [],
        bannedIps: []
      }
    ],
    modsByServer: {
      "Modded-Fabric": [
        {
          id: "fabric-api",
          name: "Fabric API",
          version: "0.114.0+1.21.1",
          latestCompat: "0.115.1+1.21.1",
          fileName: "fabric-api-0.114.0+1.21.1.jar",
          author: "modmuss50",
          loader: "fabric",
          platform: "Modrinth",
          size: "2.3 MB",
          modified: "2026-11-10 20:15",
          enabled: true,
          selected: false,
          desc: "核心與輕量掛鉤 API 模組（所有 Fabric 模組標準相依）"
        },
        {
          id: "lithium",
          name: "Lithium",
          version: "0.13.1",
          latestCompat: "0.13.1",
          fileName: "lithium-fabric-mc1.21.1-0.13.1.jar",
          author: "jellysquid3",
          loader: "fabric",
          platform: "Modrinth",
          size: "684 KB",
          modified: "2026-11-11 19:40",
          enabled: true,
          selected: false,
          desc: "通用遊戲邏輯、實體 AI 與區塊物理效能最佳化"
        },
        {
          id: "spark",
          name: "spark",
          version: "1.10.109",
          latestCompat: "1.10.109",
          fileName: "spark-1.10.109-fabric.jar.disabled",
          author: "Luck",
          loader: "fabric",
          platform: "Modrinth",
          size: "1.4 MB",
          modified: "2026-11-08 15:20",
          enabled: false,
          selected: false,
          desc: "CPU、記憶體分析器（目前改名為 .jar.disabled 停用中）"
        }
      ],
      "Tech-NeoForge": [
        {
          id: "jei",
          name: "Just Enough Items (JEI)",
          version: "19.21.0.247",
          latestCompat: "19.21.0.247",
          fileName: "jei-1.21.1-neoforge-19.21.0.247.jar",
          author: "mezz",
          loader: "neoforge",
          platform: "Modrinth",
          size: "1.5 MB",
          modified: "2026-11-05 14:10",
          enabled: true,
          selected: false,
          desc: "物品配方與合成表查詢核心模組"
        }
      ]
    },
    selectedOnlineModId: null,
    installQueue: []
  };
}
