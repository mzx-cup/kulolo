/* ═══════════════════════════════════════════════════════════════════
   手机遥控台 · 场景工坊
   纯前端三件套：无构建、无依赖。
   - 场景目录：搜索 / 分组筛选 / 折叠 / 最近使用 / 键盘切换
   - 工作区：选中场景 → 运行 → 观察步骤、日志、手机画面
   ═══════════════════════════════════════════════════════════════════ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const pad2 = (n) => String(n).padStart(2, "0");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]
));
const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const STORE = {
  theme: "ui.theme",
  shotGap: "shotGapSec",
  last: "ui.lastScenario",
  recent: "ui.recent",
  collapsed: "ui.collapsedGroups",
};

const TONES = [
  "var(--tone-amber)", "var(--tone-rose)", "var(--tone-jade)",
  "var(--tone-blue)", "var(--tone-violet)", "var(--tone-cyan)",
  "var(--tone-orange)",
];

/* 卡片图标：按 tag/标题关键词自动挑一个，后端以后传 icon 也会优先用 */
const ICONS = {
  cake: '<path d="M4 20h16M5.5 20v-5.6a2.5 2.5 0 0 1 2.5-2.5h8a2.5 2.5 0 0 1 2.5 2.5V20M4 16c1.2 0 1.8-.9 3-.9s1.8.9 3 .9 1.8-.9 3-.9 1.8.9 3 .9 1.8-.9 3-.9 1.8.9 3 .9M8 11.9V9.4M12 11.9V8M16 11.9V9.4M8 6.2V5.4M12 5.8V5M16 6.2V5.4"/>',
  heart: '<path d="M12 20.4S4.6 16 4.6 10.9A4.1 4.1 0 0 1 12 8.2a4.1 4.1 0 0 1 7.4 2.7c0 5.1-7.4 9.5-7.4 9.5z"/>',
  exam: '<path d="M2.4 9.2 12 5l9.6 4.2L12 13.4z"/><path d="M6.2 11.2v4.6c0 1.7 2.6 3 5.8 3s5.8-1.3 5.8-3v-4.6M21.6 9.2v5.4"/>',
  ticket: '<path d="M3.2 9.4a2 2 0 0 0 0 3.8v2.2a2.2 2.2 0 0 0 2.2 2.2h13.2a2.2 2.2 0 0 0 2.2-2.2v-2.2a2 2 0 0 1 0-3.8V7.2A2.2 2.2 0 0 0 18.6 5H5.4a2.2 2.2 0 0 0-2.2 2.2z"/><path d="M14 5.2v13.4"/>',
  pin: '<path d="M12 21s7-6.3 7-11.2a7 7 0 1 0-14 0C5 14.7 12 21 12 21z"/><circle cx="12" cy="9.6" r="2.5"/>',
  lantern: '<path d="M9.2 3.2h5.6M8 7.2h8M6.2 10.4c0 4 1.8 6.6 5.8 8 4-1.4 5.8-4 5.8-8zM12 18.4v2.2M9 20.6h6M12 7.2v3.2"/>',
  spark: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.6 15.6l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
  calendar: '<rect x="3.4" y="5" width="17.2" height="15.4" rx="2.4"/><path d="M3.4 10h17.2M8 3v4M16 3v4"/>',
  gift: '<rect x="4" y="9" width="16" height="11" rx="2"/><path d="M3 9h18v4H3zM12 9v11M12 9c-3.6 0-5.4-1.3-5.4-3.2S8 3 9.2 3.9 12 9 12 9zm0 0c3.6 0 5.4-1.3 5.4-3.2S16 3 14.8 3.9 12 9 12 9z"/>',
  star: '<path d="m12 3.4 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
  moon: '<path d="M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8a8.6 8.6 0 1 0 10.8 10.8z"/>',
  clock: '<circle cx="12" cy="12.4" r="7.8"/><path d="M12 8.2v4.6l3.1 2M7.4 4.8 5.6 3M16.6 4.8 18.4 3M8.2 2.8h7.6"/>',
  car: '<path d="M4.2 16.5h15.6M5.6 16.5l1-4.6a2 2 0 0 1 2-1.6h6.8a2 2 0 0 1 2 1.6l1 4.6M6.6 16.5v2.1M17.4 16.5v2.1M7.2 13.4h9.6"/><circle cx="7.8" cy="16.5" r="1.1"/><circle cx="16.2" cy="16.5" r="1.1"/>',
  food: '<path d="M4 12h16a6 6 0 0 1-6 6h-4a6 6 0 0 1-6-6zM7.2 9.2c0-1.4 1-1.9 1-3.4M12 9.2c0-1.4 1-1.9 1-3.4M16.8 9.2c0-1.4 1-1.9 1-3.4M3 20.2h18"/>',
  satellite: '<path d="M4.5 19.5 8 16M4.8 13.2a8.2 8.2 0 0 1 6-6M7.8 16.2a4.4 4.4 0 0 1 3.2-3.2M10.2 10.2l3.6-3.6 3.6 3.6-3.6 3.6zM14 6.4 17.6 2.8M16.6 9 21.2 6.4M14.4 13.8l3 3"/>',
  wave: '<path d="M3 15c2.2 0 2.2-6 4.5-6s2.2 6 4.5 6 2.2-6 4.5-6 2.2 6 4.5 6"/>',
  flame: '<path d="M12 21c3.7 0 6.4-2.5 6.4-6.1 0-4.6-4.1-6.4-3.3-11.9-3 .6-5.2 3.3-5.2 5.7 0 1.2.5 2.2 1.2 3.1-1 .1-2.6-1-2.6-3.4C6.1 10.2 5.6 12.4 5.6 15c0 3.6 2.7 6 6.4 6z"/>',
  report: '<path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h5"/>',
};

function glyphFor(s) {
  const key = s.icon && ICONS[s.icon] ? s.icon : (() => {
    const t = `${s.id || ""} ${s.tag || ""} ${s.title || ""}`.toLowerCase();
    if (/taxi|打车|yango|car/.test(t)) return "car";
    if (/food|点餐|外卖|foodpanda|restaurant/.test(t)) return "food";
    if (/satellite|卫星|玩机/.test(t)) return "satellite";
    if (/alarm|clock|闹钟|起床|时间管理/.test(t)) return "clock";
    if (/birthday|生日|cake/.test(t)) return "cake";
    if (/anniversary|纪念/.test(t)) return "heart";
    if (/exam|考试/.test(t)) return "exam";
    if (/show|concert|观演|追星|演出/.test(t)) return "ticket";
    if (/festival|节日|春节|中秋|端午|国庆|圣诞|新年|冬至/.test(t)) return "lantern";
    if (/important|重要/.test(t)) return "pin";
    if (/gift|礼/.test(t)) return "gift";
    if (/weather|天气/.test(t)) return "wave";
    if (/night|夜/.test(t)) return "moon";
    return "spark";
  })();
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[key]}</svg>`;
}

/* ── 元素引用 ───────────────────────────────────────────────────── */
const els = {
  run: $("#btn-run"), runstate: $("#runstate"), prog: $("#prog"),
  progPct: $("#prog-pct"),
  elapsed: $("#elapsed"), steps: $("#steps"), countdown: $("#countdown"),
  log: $("#log"), logcount: $("#logcount"), shot: $("#shot"), shottag: $("#shottag"),
  screen: $("#device-screen"), toast: $("#toast"),
  devstatus: $("#devstatus"), devpick: $("#devpick"), scrcpy: $("#btn-scrcpy"),
  shotBtn: $("#btn-shot"), shotDock: $("#btn-shot-dock"), expand: $("#btn-expand"),
  devMeta: $("#dev-meta"),
  cards: $("#cards"), eyebrow: $("#sc-eyebrow"), groupName: $("#sc-group"),
  title: $("#sc-title"), desc: $("#sc-desc"), spec: $("#spec"), params: $("#params"),
  hero: $("#hero"), heroMain: $(".hero-main"),
  verify: $("#verify"), resultFx: $("#result-fx"),
  btnSuccess: $("#btn-success"), btnFail: $("#btn-fail"),
  ask: $("#ask"), askPrompt: $("#ask-prompt"),
  btnAskYes: $("#btn-ask-yes"), btnAskNo: $("#btn-ask-no"),
  retry: $("#retry"), btnRetryYes: $("#btn-retry-yes"), btnRetryNo: $("#btn-retry-no"),
  stopModal: $("#stop-confirm"), btnStopYes: $("#btn-stop-yes"), btnStopNo: $("#btn-stop-no"),
  ctrlBtns: $("#ctrl-btns"), btnPause: $("#btn-pause"), btnStop: $("#btn-stop"),
  shotGap: $("#shot-gap"), shotState: $("#shot-state"),
  search: $("#sc-search"), searchWrap: $("#search-wrap"), searchClear: $("#search-clear"),
  filters: $("#filters"), recent: $("#recent"), recentChips: $("#recent-chips"),
  noResults: $("#no-results"), btnClearFilter: $("#btn-clear-filter"),
  total: $("#sc-total"), catalog: $("#catalog"), catalogScroll: $("#catalog-scroll"),
  scrim: $("#scrim"), btnCatalog: $("#btn-catalog"), btnCloseCatalog: $("#btn-close-catalog"),
  btnClearLog: $("#btn-clear-log"), btnReset: $("#btn-reset"),
  themeToggle: $("#theme-toggle"), themeColor: $("#theme-color"),
  shotView: $("#shot-view"), shotViewImg: $("#shot-view-img"), shotCap: $("#shot-cap"),
  btnCloseShot: $("#btn-close-shot"),
};

/* ── 状态 ───────────────────────────────────────────────────────── */
let scenarios = [];
let groups = [];
let selected = null;
let activeFilter = "all";
let query = "";
let collapsed = new Set(Array.isArray(readJSON(STORE.collapsed, [])) ? readJSON(STORE.collapsed, []) : []);
let recent = Array.isArray(readJSON(STORE.recent, [])) ? readJSON(STORE.recent, []) : [];
let lastId = 0;
let eventsPrimed = false;
let logLines = 0;
let wasRunning = false;
let startingRun = false;
let lastConnected = null;
let firstShotTried = false;
let runStart = 0;
let runEstimateSec = 0;
let progressPct = 0;
let elapsedTimer = null;
let elapsedClearTimer = null;
let shotUrl = null;
let shotInFlight = false;
let lastShotTag = "";
let shotGap = (() => {
  let n = 5;
  try { n = Number(localStorage.getItem(STORE.shotGap)) || 5; } catch { /* ignore */ }
  return Number.isFinite(n) && n >= 1 ? Math.min(60, Math.round(n)) : 5;
})();
let shotTimer = null;
let visible = !document.hidden;
let pendingConfirm = false;
let pendingAsk = false;
let suppressStaleResult = false;
let catalogOpen = false;
let toastTimer = null;
let themeTimer = null;
let uiRunToken = 0;
let swapTimer = null;
let fxTimers = [];

const mqMobile = window.matchMedia("(max-width: 1280px)");

/* ── 小工具 ─────────────────────────────────────────────────────── */
function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}
function writeJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
}
function writeText(key, value) {
  try { localStorage.setItem(key, value); } catch { /* ignore */ }
}
function readText(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function nowText() {
  const d = new Date();
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}
function isBusy() {
  return startingRun || els.run.classList.contains("busy");
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (path === "/api/screenshot") return r;
  return r.json();
}

/* ── Toast ──────────────────────────────────────────────────────── */
function toast(msg, isErr = false) {
  els.toast.textContent = msg;
  els.toast.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { els.toast.className = "toast"; }, 3200);
}

/* ── 弹层通用 ───────────────────────────────────────────────────── */
function showModal(el, focusEl) {
  if (!el) return;
  clearTimeout(el._hideTimer);
  el.hidden = false;
  void el.offsetWidth;
  el.classList.add("show");
  if (focusEl) {
    setTimeout(() => {
      if (el.classList.contains("show")) {
        try { focusEl.focus({ preventScroll: true }); } catch { focusEl.focus(); }
      }
    }, 90);
  }
}
function hideModal(el) {
  if (!el || el.hidden) return;
  el.classList.remove("show");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => {
    if (!el.classList.contains("show")) el.hidden = true;
  }, 270);
}

/* ── 目录：分组 / 卡片渲染 ─────────────────────────────────────── */
function buildGroups() {
  const map = new Map();
  scenarios.forEach((s, i) => {
    const name = s.group || "其他场景";
    if (!map.has(name)) map.set(name, { name, list: [], tone: "" });
    s._no = i + 1;
    s._group = name;
    map.get(name).list.push(s);
  });
  let ci = 0;
  for (const g of map.values()) {
    if (/节日/.test(g.name)) g.tone = "var(--tone-rose)";
    else if (/重要|日历/.test(g.name)) g.tone = "var(--tone-amber)";
    else if (/生活服务/.test(g.name)) g.tone = "var(--tone-orange)";
    else if (/玩机技巧/.test(g.name)) g.tone = "var(--tone-cyan)";
    else if (/时间/.test(g.name)) g.tone = "var(--tone-cyan)";
    else g.tone = TONES[ci % TONES.length];
    ci += 1;
  }
  groups = [...map.values()];
}

function renderFilters() {
  const all = `<button class="filter${activeFilter === "all" ? " on" : ""}" type="button"
    data-group="all" role="button" aria-pressed="${activeFilter === "all"}">全部
    <span class="n">${scenarios.length}</span></button>`;
  const items = groups.map((g) => `
    <button class="filter${activeFilter === g.name ? " on" : ""}" type="button"
      data-group="${esc(g.name)}" role="button" aria-pressed="${activeFilter === g.name}"
      style="--g-tone:${g.tone}">
      <span class="dot"></span>${esc(g.name)}<span class="n">${g.list.length}</span>
    </button>`).join("");
  els.filters.innerHTML = all + items;
}

function currentVisible() {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return scenarios.filter((s) => {
    if (activeFilter !== "all" && s._group !== activeFilter) return false;
    if (!tokens.length) return true;
    const hay = `${s.title} ${s.tag} ${s.desc || ""} ${s._group} ${s.id}`.toLowerCase();
    return tokens.every((t) => hay.includes(t));
  });
}

function highlight(text, q) {
  const safe = esc(text);
  const tokens = q.trim().split(/\s+/).filter(Boolean).map(escapeRegExp);
  if (!tokens.length) return safe;
  try {
    return safe.replace(new RegExp(`(${tokens.join("|")})`, "gi"), "<mark>$1</mark>");
  } catch {
    return safe;
  }
}

function renderCatalog() {
  if (!scenarios.length) return;
  const visibleList = currentVisible();
  const filtering = Boolean(query.trim()) || activeFilter !== "all";
  els.total.textContent = filtering
    ? `${visibleList.length} / ${scenarios.length}`
    : `${scenarios.length} 个`;
  els.total.title = `${visibleList.length} / ${scenarios.length} 个场景`;
  els.noResults.hidden = !(scenarios.length && visibleList.length === 0);

  els.cards.innerHTML = "";
  if (!visibleList.length) {
    renderRecent();
    return;
  }

  let cursor = 0;
  for (const g of groups) {
    const list = visibleList.filter((s) => s._group === g.name);
    if (!list.length) continue;

    const closed = !filtering && collapsed.has(g.name);
    const sec = document.createElement("section");
    sec.className = "group" + (closed ? " closed" : "");
    sec.dataset.group = g.name;
    sec.style.setProperty("--g-tone", g.tone);

    const head = document.createElement("button");
    head.type = "button";
    head.className = "group-head";
    head.setAttribute("aria-expanded", String(!closed));
    head.innerHTML = `<span class="g-dot"></span>
      <span class="g-name">${esc(g.name)}</span>
      <span class="g-count">${list.length}</span>
      <svg class="g-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="m6 9 6 6 6-6"/></svg>`;

    const body = document.createElement("div");
    body.className = "group-body";
    const inner = document.createElement("div");
    inner.className = "group-inner";
    const ul = document.createElement("ul");
    ul.className = "group-list";

    for (const s of list) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      const on = Boolean(selected && s.id === selected.id);
      btn.type = "button";
      btn.className = "card" + (on ? " on" : "");
      btn.dataset.id = s.id;
      btn.setAttribute("aria-pressed", String(on));
      btn.style.setProperty("--ci", String(Math.min(cursor, 12)));
      btn.style.setProperty("--g-tone", g.tone);
      btn.title = `${s.title} · ${s.tag}`;
      btn.innerHTML = `<span class="card-glyph">${glyphFor(s)}</span>
        <span class="card-main">
          <span class="card-line">
            <span class="card-no">${pad2(s._no)}</span>
            <span class="card-title">${highlight(s.title, query)}</span>
          </span>
          <span class="card-tag">${highlight(s.tag, query)}</span>
        </span>
        <span class="card-go" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
            stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>
        </span>`;
      li.appendChild(btn);
      ul.appendChild(li);
      cursor += 1;
    }

    inner.appendChild(ul);
    body.appendChild(inner);
    sec.append(head, body);
    els.cards.appendChild(sec);
  }
  renderRecent();
}

function renderSkeleton() {
  els.cards.innerHTML = `<div class="skel-list" aria-hidden="true">
    <span class="skel"></span><span class="skel"></span><span class="skel"></span>
    <span class="skel"></span><span class="skel"></span>
  </div>`;
  els.filters.innerHTML = "";
  els.recent.hidden = true;
  els.noResults.hidden = true;
  els.total.textContent = "—";
}

function renderLoadError(msg) {
  els.cards.innerHTML = `<div class="load-error">
    <span class="le-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
        stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 8.5v5M12 17.2v.1"/><path d="M10.3 4.4 3.5 16.2A1.9 1.9 0 0 0 5.2 19h13.6a1.9 1.9 0 0 0 1.7-2.8L13.7 4.4a1.9 1.9 0 0 0-3.4 0z"/>
      </svg>
    </span>
    <b>场景读取失败</b>
    <p>${esc(msg)}</p>
    <button id="btn-reload" class="btn ghost sm" type="button">重新加载</button>
  </div>`;
  $("#btn-reload", els.cards)?.addEventListener("click", loadScenarios);
  els.total.textContent = "—";
  els.noResults.hidden = true;
}

/* ── 最近使用 ───────────────────────────────────────────────────── */
function addRecent(id) {
  recent = [id, ...recent.filter((x) => x !== id)].slice(0, 4);
  writeJSON(STORE.recent, recent);
}
function renderRecent() {
  const show = !query.trim() && activeFilter === "all" && recent.length > 0;
  if (!show) { els.recent.hidden = true; return; }
  const items = recent
    .map((id) => scenarios.find((s) => s.id === id))
    .filter(Boolean)
    .slice(0, 3);
  if (!items.length) { els.recent.hidden = true; return; }
  els.recent.hidden = false;
  els.recentChips.innerHTML = "";
  for (const s of items) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "recent-chip";
    b.textContent = s.title;
    b.title = s.title;
    b.addEventListener("click", () => {
      if (selected && selected.id === s.id && mqMobile.matches) closeCatalog();
      selectScenario(s.id);
    });
    els.recentChips.appendChild(b);
  }
}

/* ── 场景选择 ───────────────────────────────────────────────────── */
function refreshCardSelection() {
  for (const card of $$(".card", els.cards)) {
    const on = Boolean(selected && card.dataset.id === selected.id);
    card.classList.toggle("on", on);
    card.setAttribute("aria-pressed", String(on));
  }
}

function trySelect(id) {
  if (isBusy()) {
    toast("运行中，结束后再切换场景", true);
    return;
  }
  selectScenario(id);
}

function selectScenario(id, opts = {}) {
  if (isBusy() && !opts.force) {
    if (!opts.silent) toast("运行中，结束后再切换场景", true);
    return false;
  }
  const s = scenarios.find((x) => x.id === id);
  if (!s) return false;

  if (selected && selected.id === id && !opts.force) {
    refreshCardSelection();
    if (mqMobile.matches && !opts.silent) closeCatalog();
    return true;
  }

  selected = s;
  const group = groups.find((g) => g.name === s._group) || groups[0];
  if (group) {
    els.hero.style.setProperty("--g-tone", group.tone);
    els.groupName.style.setProperty("--g-tone", group.tone);
  }

  els.eyebrow.textContent = "SCENARIO " + pad2(s._no);
  els.groupName.textContent = s._group || "场景";
  els.title.textContent = s.title;
  els.desc.textContent = s.desc || "";

  pendingConfirm = false;
  pendingAsk = false;
  hideModal(els.verify);
  hideModal(els.ask);
  hideModal(els.retry);
  hideModal(els.stopModal);

  renderParams();
  renderSpec();
  startRunUi();

  els.run.disabled = false;
  els.run.classList.remove("busy");
  $(".lbl", els.run).textContent = "一键运行";
  els.runstate.className = "runstate idle";
  els.runstate.textContent = "就绪。点按钮后全程自动，请勿拔线。";
  els.ctrlBtns.hidden = true;

  document.title = `${s.title} · 手机遥控台`;
  writeText(STORE.last, s.id);
  addRecent(s.id);
  refreshCardSelection();
  renderRecent();
  scrollActiveCard(s.id, opts.silent);

  if (!opts.silent) {
    els.heroMain.classList.remove("swap");
    void els.heroMain.offsetWidth;
    els.heroMain.classList.add("swap");
    clearTimeout(swapTimer);
    swapTimer = setTimeout(() => els.heroMain.classList.remove("swap"), 520);
  }

  if (mqMobile.matches && !opts.silent) closeCatalog();
  return true;
}

function scrollActiveCard(id, instant) {
  const card = $$(".card", els.cards).find((c) => c.dataset.id === id);
  if (!card) return;
  const box = els.catalogScroll;
  const cr = card.getBoundingClientRect();
  const br = box.getBoundingClientRect();
  if (cr.top < br.top + 4 || cr.bottom > br.bottom - 4) {
    const behavior = instant ? "auto" : "smooth";
    box.scrollTo({ top: box.scrollTop + (cr.top - br.top) - 8, behavior });
  }
}

/* ── 参数 / 摘要 ────────────────────────────────────────────────── */
function renderParams() {
  els.params.innerHTML = "";
  const params = selected?.params || [];
  els.btnReset.hidden = params.length === 0;
  if (!params.length) {
    const span = document.createElement("span");
    span.className = "no-params";
    span.textContent = "这个场景没有可调参数，直接点「一键运行」即可。";
    els.params.appendChild(span);
    return;
  }

  params.forEach((p, i) => {
    const lab = document.createElement("label");
    lab.className = "field" + (p.type === "text" ? " grow" : "");
    lab.style.setProperty("--i", String(i));

    const label = document.createElement("span");
    label.className = "lbl";
    label.textContent = p.label || "";
    lab.appendChild(label);

    if (p.type === "number") {
      const inp = document.createElement("input");
      inp.type = "number";
      inp.id = "p-" + p.key;
      inp.value = String(p.value ?? "");
      inp.inputMode = "numeric";
      if (p.min != null) inp.min = p.min;
      if (p.max != null) inp.max = p.max;
      lab.appendChild(inp);
      if (p.unit) {
        const u = document.createElement("span");
        u.className = "unit";
        u.textContent = p.unit;
        lab.appendChild(u);
      }
    } else if (p.type === "time") {
      const h = document.createElement("input");
      h.type = "number";
      h.id = "p-" + p.key + "-hour";
      h.value = String(p.h ?? 9);
      h.min = 0; h.max = 23;
      h.className = "w2";
      h.inputMode = "numeric";
      h.setAttribute("aria-label", (p.label || "时间") + " · 时");

      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = ":";

      const m = document.createElement("input");
      m.type = "number";
      m.id = "p-" + p.key + "-min";
      m.value = String(p.m ?? 30);
      m.min = 0; m.max = 59;
      m.className = "w2";
      m.inputMode = "numeric";
      m.setAttribute("aria-label", (p.label || "时间") + " · 分");

      lab.append(h, sep, m);
    } else {
      const inp = document.createElement("input");
      inp.type = "text";
      inp.id = "p-" + p.key;
      inp.placeholder = p.placeholder || "";
      inp.autocomplete = "off";
      inp.spellcheck = false;
      lab.appendChild(inp);
    }
    els.params.appendChild(lab);
  });
}

function renderSpec() {
  if (!selected) return;
  els.spec.innerHTML = "";
  for (const sp of selected.specs || []) {
    const li = document.createElement("li");
    const k = document.createElement("span");
    k.className = "k";
    k.textContent = sp.k;
    const v = document.createElement("span");
    v.className = "v";
    if (sp.from) {
      const inp = $("#p-" + sp.from);
      const val = inp ? inp.value : "";
      v.textContent = `${sp.prefix || ""}${val}${sp.suffix || ""}`;
      v.classList.add("pop");
    } else {
      v.textContent = sp.v ?? "";
    }
    li.append(k, v);
    els.spec.appendChild(li);
  }
}

function collectParams() {
  const body = {};
  if (!selected) return body;
  for (const p of selected.params || []) {
    if (p.type === "time") {
      const h = $("#p-" + p.key + "-hour");
      const m = $("#p-" + p.key + "-min");
      if (h) body.hour = Number(h.value);
      if (m) body.minute = Number(m.value);
    } else {
      const inp = $("#p-" + p.key);
      if (!inp) continue;
      const v = inp.value.trim();
      if (v !== "") body[p.key] = p.type === "number" ? Number(v) : v;
    }
  }
  return body;
}

/* ── 运行 UI 重置 ───────────────────────────────────────────────── */
const STEPS_PLACEHOLDER = `<li class="placeholder">
  <span class="ph-glyph" aria-hidden="true">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3"
      stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.2"/>
      <path d="M12 3.5v3M12 17.5v3M3.5 12h3M17.5 12h3"/>
    </svg>
  </span>
  <span>点击「一键运行」后<br>步骤会在这里逐条点亮</span>
  <em class="ph-tip">运行时可随时暂停或结束，右侧画面会自动刷新</em>
</li>`;

function clearFxTimers() {
  for (const t of fxTimers) clearTimeout(t);
  fxTimers = [];
}

function startRunUi() {
  uiRunToken += 1;
  clearFxTimers();
  els.steps.innerHTML = STEPS_PLACEHOLDER;
  els.steps.classList.remove("live");
  els.log.innerHTML = "";
  logLines = 0;
  els.logcount.textContent = "";
  els.countdown.textContent = "";
  els.countdown.classList.remove("live");
  els.prog.className = "bar";
  els.prog.style.width = "0%";
  if (els.progPct) els.progPct.textContent = "0%";
  els.elapsed.textContent = "00:00";
  runStart = 0;
  runEstimateSec = 0;
  progressPct = 0;
  clearInterval(elapsedTimer);
  clearTimeout(elapsedClearTimer);
  els.ctrlBtns.hidden = true;
  hideModal(els.verify);
  hideModal(els.ask);
  hideModal(els.retry);
  hideModal(els.stopModal);
  pendingConfirm = false;
  pendingAsk = false;
  els.hero.classList.remove("is-done", "is-fail");
  els.resultFx.hidden = true;
  els.resultFx.className = "result-fx ok";
  els.resultFx.innerHTML = "";
  /* 选场景 / 新开跑时，先别把上一轮遗留的 result 当成这一轮的结论 */
  suppressStaleResult = true;
}

/* ── 日志 ───────────────────────────────────────────────────────── */
function appendLine(kind, text) {
  const nearBottom = els.log.scrollHeight - els.log.scrollTop - els.log.clientHeight < 80;
  const line = document.createElement("div");
  line.className = "logline " + kind;
  const ts = document.createElement("span");
  ts.className = "ts";
  ts.textContent = nowText();
  const msg = document.createElement("span");
  msg.className = "msg";
  msg.textContent = text;
  line.append(ts, msg);
  els.log.appendChild(line);
  while (els.log.childElementCount > 600) els.log.firstElementChild.remove();
  logLines = els.log.childElementCount;
  els.logcount.textContent = logLines ? `${logLines} 行` : "";
  if (nearBottom) {
    requestAnimationFrame(() => { els.log.scrollTop = els.log.scrollHeight; });
  }
}

function clearLog() {
  els.log.innerHTML = "";
  logLines = 0;
  els.logcount.textContent = "";
}

/* ── 步骤 ───────────────────────────────────────────────────────── */
function stepNode(no) {
  const li = document.createElement("li");
  li.id = "step-" + no;
  li.className = "doing";
  li.innerHTML = `<span class="no">
      <span class="num">${pad2(no)}</span>
      <svg class="tick" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 8.4 6.4 11.6 12.8 4.6"/></svg>
      <svg class="cross" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>
    </span>
    <span class="body"><b></b><span class="ms"></span></span>`;
  return li;
}

function scrollStepIntoView(li) {
  if (!li) return;
  const box = els.steps;
  const lr = li.getBoundingClientRect();
  const br = box.getBoundingClientRect();
  if (lr.top < br.top + 6 || lr.bottom > br.bottom - 6) {
    box.scrollTo({ top: box.scrollTop + (lr.top - br.top) - 12, behavior: "smooth" });
  }
}

function renderEvent(e, run) {
  switch (e.t) {
    case "step": {
      const li = document.getElementById("step-" + e.no);
      if (e.state === "start") {
        $(".placeholder", els.steps)?.remove();
        els.steps.classList.add("live");
        const node = stepNode(e.no);
        $("b", node).textContent = e.title || "";
        els.steps.appendChild(node);
        appendLine("evt", `[${pad2(e.no)}] ${e.title || ""}`);
        scrollStepIntoView(node);
      } else if (li) {
        li.className = e.state === "ok" ? "ok" : "fail";
        $(".ms", li).textContent = `${e.ms ?? 0}ms ${e.detail || ""}`.trim();
        appendLine(e.state === "ok" ? "ok" : "err", `${e.detail || ""}`.trim());
        scrollStepIntoView(li);
      }
      break;
    }
    case "log":
      appendLine("detail", "· " + (e.msg || ""));
      break;
    case "shot":
      setShot("data:image/png;base64," + e.png_b64, `#${pad2(e.no)} ${e.tag || ""}`);
      break;
    case "tick":
      els.countdown.textContent = `息屏 ${e.remain}s`;
      els.countdown.classList.add("live");
      break;
    case "error":
      appendLine("err", "!! " + (e.msg || ""));
      toast("执行失败：" + (e.msg || "未知错误"), true);
      break;
    case "done":
      els.countdown.classList.remove("live");
      break;
    case "confirm":
      /* 页面重载时服务端可能还留着历史事件；只在任务确实仍在等待时弹确认 */
      if (!run || !run.running) break;
      pendingConfirm = true;
      appendLine("detail", "等待确认：卡片是否已成功触发？");
      setTimeout(() => { if (pendingConfirm) showVerify(); }, 280);
      break;
    case "ask":
      if (!run || !run.running) break;
      pendingAsk = true;
      if (e.prompt) els.askPrompt.textContent = e.prompt;
      appendLine("detail", "等待回答：卡片前置条件是否满足？");
      setTimeout(() => { if (pendingAsk) showAsk(); }, 280);
      break;
    case "pause":
      appendLine("detail", "▮▮ 已暂停（可点「继续」恢复）");
      els.btnPause.textContent = "继续";
      break;
    case "resume":
      appendLine("detail", "▶ 已继续执行");
      els.btnPause.textContent = "暂停";
      break;
    case "stop":
      appendLine("detail", "■ 用户请求结束场景");
      break;
    default:
      break;
  }
}

/* ── 轮询运行事件 ───────────────────────────────────────────────── */
function estimateRunSeconds(s, params) {
  /* 进度条按“已用时间 / 预估总时长”平滑推进；长等待（warmup/wait_sec）
     会计入预估，所以 10 分钟预热不会几秒就冲到 100%。 */
  let sec = 30;
  const wait = Number(params && params.wait_sec);
  if (Number.isFinite(wait)) sec += Math.max(0, wait);
  const warm = Number(params && params.warmup_min);
  if (Number.isFinite(warm)) sec += Math.max(0, warm) * 60;
  if (s && /anniversary/.test(s.id)) sec += 60;
  if (s && /^festival_/.test(s.id)) sec += 15;
  if (s && /^(greeting|birthday|anniversary|important_day|show_day)/.test(s.id)) {
    sec += 45; // 首次 seed 可能走一次日历 UI；fast 路径会提前结束，影响不大
  }
  return Math.max(25, sec);
}

function updateRunProgress() {
  if (!runStart || !runEstimateSec) return;
  const elapsed = (Date.now() - runStart) / 1000;
  const p = 0.95 * (1 - Math.exp(-1.7 * elapsed / Math.max(15, runEstimateSec)));
  if (p <= progressPct) return;
  progressPct = Math.min(0.95, p);
  els.prog.style.width = (progressPct * 100).toFixed(1) + "%";
  if (els.progPct) els.progPct.textContent = Math.round(progressPct * 100) + "%";
}

function tickElapsed() {
  if (!runStart) return;
  const s = Math.floor((Date.now() - runStart) / 1000);
  els.elapsed.textContent = `${pad2(Math.floor(s / 60))}:${pad2(s % 60)}`;
  updateRunProgress();
}

async function poll() {
  let d;
  try {
    d = await api("/api/events?after=" + lastId);
  } catch {
    return;
  }
  if (!d || !d.run) return;
  const run = d.run;
  /* 首次轮询时如果服务端没在跑任务，就把历史事件直接标记为已读，
     避免一刷新页面就被上一轮的长日志刷屏。 */
  const skipHistory = !eventsPrimed && !run.running;
  eventsPrimed = true;
  for (const e of (Array.isArray(d.events) ? d.events : [])) {
    lastId = Math.max(lastId, e.id);
    if (!skipHistory) renderEvent(e, run);
  }

  if (run.running) {
    startingRun = false;
    suppressStaleResult = false;
    if (!wasRunning) {
      wasRunning = true;
      clearInterval(elapsedTimer);
      clearTimeout(elapsedClearTimer);
      runEstimateSec = estimateRunSeconds(selected, collectParams());
      progressPct = 0;
      els.prog.style.width = "0%";
      if (els.progPct) els.progPct.textContent = "0%";
      runStart = Date.now();
      els.elapsed.textContent = "00:00";
      elapsedTimer = setInterval(tickElapsed, 250);
      shotStateTick();
    }
    els.run.disabled = true;
    els.run.classList.add("busy");
    $(".lbl", els.run).textContent = "运行中";
    els.ctrlBtns.hidden = false;
    els.btnPause.textContent = run.paused ? "继续" : "暂停";
    els.prog.classList.remove("ok", "fail", "indeterminate");
    els.screen.classList.add("live");
    els.runstate.className = "runstate doing";
    els.runstate.textContent = run.paused
      ? "已暂停…点「继续」恢复"
      : "运行中…请勿拔线、勿手动操作手机。";
  } else {
    if (startingRun && (run.result || run.error)) {
      startingRun = false;
      /* 我们自己刚发起的这一轮已经结算，结果就是新的 */
      suppressStaleResult = false;
    }
    els.screen.classList.remove("live");
    els.ctrlBtns.hidden = true;

    if (wasRunning) {
      wasRunning = false;
      suppressStaleResult = false;
      clearInterval(elapsedTimer);
      clearTimeout(elapsedClearTimer);
      els.countdown.textContent = "";
      els.countdown.classList.remove("live");
      elapsedClearTimer = setTimeout(() => {
        if (!wasRunning) els.elapsed.textContent = "";
      }, 1600);
      shotStateTick();

      const token = uiRunToken;
      const sid = selected?.id;
      if (run.result && !run.error && !pendingConfirm) {
        if (run.result.confirmed_ok === true) {
          setTimeout(() => {
            if (token !== uiRunToken || wasRunning) return;
            successSettle();
          }, 900);
        } else if (run.result.confirmed_ok === false) {
          const canRetry = Boolean(selected) && (
            typeof selected.retryable === "boolean"
              ? selected.retryable
              : RETRYABLE.has(selected.id)
          );
          setTimeout(() => {
            if (token !== uiRunToken || wasRunning) return;
            if (selected?.id !== sid) return;
            if (canRetry) showRetry();
            else failSettle();
          }, 900);
        }
      }
    }

    if (!startingRun) {
      els.run.disabled = false;
      els.run.classList.remove("busy");
      $(".lbl", els.run).textContent = "一键运行";
      els.prog.classList.remove("indeterminate");
      if (!suppressStaleResult && run.error) {
        els.prog.style.width = "100%";
        if (els.progPct) els.progPct.textContent = "100%";
        els.prog.classList.remove("ok");
        els.prog.classList.add("fail");
        els.runstate.className = "runstate fail";
        els.runstate.textContent = "失败：" + run.error;
      } else if (!suppressStaleResult && run.result) {
        els.prog.style.width = "100%";
        if (els.progPct) els.progPct.textContent = "100%";
        els.prog.classList.remove("fail");
        els.prog.classList.add("ok");
        els.runstate.className = "runstate ok";
        els.runstate.textContent = run.result.summary || "完成。";
      }
    }
  }
}

/* ── 启动场景 ───────────────────────────────────────────────────── */
async function runScenario(extra = {}) {
  if (!selected || isBusy()) return;
  const params = collectParams();
  startingRun = true;
  startRunUi();
  runEstimateSec = estimateRunSeconds(selected, params);

  els.run.disabled = true;
  els.run.classList.add("busy");
  $(".lbl", els.run).textContent = "启动中…";
  els.runstate.className = "runstate doing";
  els.runstate.textContent = "正在启动场景…";
  els.prog.style.width = "0%";

  try {
    const r = await api("/api/scenario/" + encodeURIComponent(selected.id), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...params, ...extra }),
    });
    if (r.error) {
      startingRun = false;
      els.run.disabled = false;
      els.run.classList.remove("busy");
      $(".lbl", els.run).textContent = "一键运行";
      els.prog.classList.remove("indeterminate");
      els.runstate.className = "runstate fail";
      els.runstate.textContent = r.error;
      appendLine("err", "!! " + r.error);
      toast(r.error, true);
    } else {
      toast("已开始，全程自动执行");
      els.runstate.className = "runstate doing";
      els.runstate.textContent = "已启动，正在接管手机…";
    }
  } catch {
    startingRun = false;
    els.run.disabled = false;
    els.run.classList.remove("busy");
    $(".lbl", els.run).textContent = "一键运行";
    els.prog.classList.remove("indeterminate");
    els.runstate.className = "runstate fail";
    els.runstate.textContent = "启动失败：本地服务无响应";
    toast("启动失败：本地服务无响应", true);
  }
}

/* ── 确认 / 询问 / 重试 / 停止 ─────────────────────────────────── */
function showVerify() {
  showModal(els.verify, els.btnSuccess);
  appendLine("detail", "等待确认：卡片是否已成功触发？");
}
function showAsk() {
  showModal(els.ask, els.btnAskYes);
  appendLine("detail", "等待回答：OOBE 国家是否已调整到中国？");
}
function showRetry() {
  hideModal(els.verify);
  showModal(els.retry, els.btnRetryYes);
}

async function confirmAnswer(ok) {
  hideModal(els.verify);
  pendingConfirm = false;
  els.btnSuccess.disabled = true;
  els.btnFail.disabled = true;
  try {
    const r = await api("/api/scenario/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ok }),
    });
    if (r.error) {
      pendingConfirm = true;
      showModal(els.verify, els.btnSuccess);
      toast(r.error, true);
      return;
    }
    appendLine(ok ? "ok" : "err",
      ok ? "已确认：卡片成功触发，继续执行" : "已确认：卡片未触发，继续执行");
  } catch {
    pendingConfirm = true;
    showModal(els.verify, els.btnSuccess);
    toast("确认失败：本地服务无响应", true);
  } finally {
    els.btnSuccess.disabled = false;
    els.btnFail.disabled = false;
  }
}

async function askAnswer(ok) {
  hideModal(els.ask);
  pendingAsk = false;
  els.btnAskYes.disabled = true;
  els.btnAskNo.disabled = true;
  try {
    const r = await api("/api/scenario/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ok }),
    });
    if (r.error) {
      pendingAsk = true;
      showModal(els.ask, els.btnAskYes);
      toast(r.error, true);
      return;
    }
    appendLine(ok ? "ok" : "err",
      ok ? "已确认：前置条件满足，继续触发" : "已确认：前置条件不满足，场景将中止");
  } catch {
    pendingAsk = true;
    showModal(els.ask, els.btnAskYes);
    toast("回答失败：本地服务无响应", true);
  } finally {
    els.btnAskYes.disabled = false;
    els.btnAskNo.disabled = false;
  }
}

async function pauseOrResume() {
  const pausing = els.btnPause.textContent === "暂停";
  try {
    const r = await api("/api/scenario/" + (pausing ? "pause" : "resume"), { method: "POST" });
    if (r.error) toast(r.error, true);
  } catch {
    toast("操作失败：本地服务无响应", true);
  }
}

async function stopRun() {
  hideModal(els.stopModal);
  try {
    const r = await api("/api/scenario/stop", { method: "POST" });
    if (r.error) toast(r.error, true);
    else toast("已请求结束当前场景");
  } catch {
    toast("操作失败：本地服务无响应", true);
  }
}

/* ── 结算动效 ───────────────────────────────────────────────────── */
function successFX() {
  return `
  <div class="rt-card">
    <span class="rt-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.2 4.2L19 6.8"/></svg>
    </span>
    <span class="rt-copy">
      <b>卡片已成功触发</b>
      <small>流程全部生效 · 锁屏卡片确认出现</small>
    </span>
  </div>`;
}
function failFX() {
  return `
  <div class="rt-card">
    <span class="rt-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round"><path d="M7 7l10 10M17 7 7 17"/></svg>
    </span>
    <span class="rt-copy">
      <b>卡片未触发</b>
      <small>已记录本次结果 · 可调整参数后重试</small>
    </span>
  </div>`;
}

function spawnBits(container, kind, n) {
  if (!container) return;
  for (let i = 0; i < n; i++) {
    const b = document.createElement("span");
    b.className = kind;
    if (kind === "confetti") {
      const s = 6 + Math.random() * 6;
      b.style.width = b.style.height = s.toFixed(0) + "px";
      b.style.background = ["#6fd6b0", "#9cebd0", "#e8b264", "#ffd28f", "#f4ecdc"][i % 5];
      b.style.borderRadius = i % 3 ? "2px" : "50%";
      b.style.setProperty("--dx", (Math.random() * 280 - 140).toFixed(0) + "px");
      b.style.setProperty("--dy", (Math.random() * 160 - 215).toFixed(0) + "px");
      b.style.setProperty("--r", (Math.random() * 540 - 270).toFixed(0) + "deg");
    } else {
      const s = 3 + Math.random() * 4;
      b.style.width = b.style.height = s.toFixed(0) + "px";
      b.style.background = ["#6b5b45", "#8a7860", "#a8321f", "#b8ac98"][i % 4];
      b.style.setProperty("--dx", (Math.random() * 120 - 60).toFixed(0) + "px");
      b.style.setProperty("--dy", (60 + Math.random() * 150).toFixed(0) + "px");
    }
    b.style.setProperty("--d", (Math.random() * 300).toFixed(0) + "ms");
    container.appendChild(b);
  }
}

function successSettle() {
  hideModal(els.verify);
  pendingConfirm = false;
  clearFxTimers();
  const fx = els.resultFx;
  fx.className = "result-fx ok";
  fx.innerHTML = successFX();
  fx.hidden = false;
  const hold = 3000;
  fxTimers = [
    setTimeout(() => fx.classList.add("out"), hold),
    setTimeout(() => {
      fx.hidden = true;
      fx.classList.remove("out");
    }, hold + 650),
  ];
}

function failSettle() {
  hideModal(els.verify);
  hideModal(els.retry);
  pendingConfirm = false;
  clearFxTimers();
  const fx = els.resultFx;
  fx.className = "result-fx fail";
  fx.innerHTML = failFX();
  fx.hidden = false;
  const hold = 2600;
  fxTimers = [
    setTimeout(() => fx.classList.add("out"), hold),
    setTimeout(() => {
      fx.hidden = true;
      fx.classList.remove("out");
    }, hold + 650),
  ];
}

const RETRYABLE = new Set([
  "greeting", "birthday", "anniversary", "anniversary_greeting",
  "exam", "exam_greeting", "show_day", "important_day",
]);

/* ── 设备状态 ───────────────────────────────────────────────────── */
const shortSerial = (s) => (s.length > 12 ? "…" + s.slice(-8) : s);

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const conn = Boolean(s.connected);
    if (conn) {
      els.devstatus.className = "devstatus on";
      const label = `${s.model || "Android"} · ${s.serial}` + (s.keyguard ? " · 锁屏中" : "");
      $(".txt", els.devstatus).textContent = label;
      els.devstatus.title = `${s.model || ""} · ${s.serial}\n点击立即重新检测设备`;
      els.devstatus.setAttribute("aria-label", `${label}，已连接。点击重新检测设备`);
      els.devMeta.textContent = `${s.width || "?"} × ${s.height || "?"} · ${s.keyguard ? "锁屏" : "亮屏"}`;
    } else {
      els.devstatus.className = "devstatus off";
      const label = s.serial ? `设备异常 · ${s.serial}` : "未连接设备";
      $(".txt", els.devstatus).textContent = label;
      els.devstatus.title = s.error || "点击重新检测设备";
      els.devstatus.setAttribute("aria-label", `${label}。点击重新检测设备`);
      els.devMeta.textContent = "等待设备接入…";
    }

    if (lastConnected !== null && lastConnected !== conn) {
      toast(conn ? "已自动连接设备" : (s.error || "设备断开，自动重连中…"), !conn);
    }
    lastConnected = conn;

    els.scrcpy.disabled = !s.scrcpy;
    els.scrcpy.title = s.scrcpy || "未找到 scrcpy.exe（可用 python main.py --scrcpy <路径> 指定）";
    renderDevPicker(s);
    shotStateTick();

    /* 设备刚连上时主动抓一帧，别让右侧空等自动刷新 */
    if (conn && !firstShotTried && !wasRunning && !startingRun
        && !els.screen.classList.contains("has-shot")) {
      firstShotTried = true;
      setTimeout(() => {
        if (visible && lastConnected && !wasRunning && !startingRun) {
          fetchShot("初始画面 " + new Date().toLocaleTimeString());
        }
      }, 420);
    }
  } catch {
    els.devstatus.className = "devstatus off";
    $(".txt", els.devstatus).textContent = "服务无响应";
    els.devstatus.setAttribute("aria-label", "本地服务无响应。点击重新检测设备");
    els.devMeta.textContent = "本地服务无响应";
    if (lastConnected !== false) {
      toast("服务无响应，正在重试…", true);
      lastConnected = false;
    }
    els.scrcpy.disabled = true;
    els.devpick.hidden = true;
    shotStateTick();
  }
}

function renderDevPicker(s) {
  const devs = (s.devices || []).filter((d) => d.state === "device");
  if (devs.length < 2) {
    els.devpick.hidden = true;
    els.devpick.innerHTML = "";
    return;
  }
  els.devpick.hidden = false;
  els.devpick.innerHTML = "";
  for (const d of devs) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip" + (d.serial === s.selected ? " on" : "");
    chip.textContent = shortSerial(d.serial);
    chip.title = d.serial;
    chip.addEventListener("click", () => pickDevice(d.serial, chip));
    els.devpick.appendChild(chip);
  }
}

async function pickDevice(serial, chip) {
  try {
    const r = await api("/api/device", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ serial }),
    });
    if (r.error) return toast("选择设备失败：" + r.error, true);
    els.devpick.querySelectorAll(".chip").forEach((c) => c.classList.remove("on"));
    chip.classList.add("on");
    appendLine("detail", `切换到设备 ${serial}`);
    refreshStatus();
  } catch {
    toast("选择设备失败：本地服务无响应", true);
  }
}

/* ── 截图 ───────────────────────────────────────────────────────── */
function setShot(src, tag) {
  const pre = new Image();
  pre.onload = () => {
    els.shot.src = src;
    els.screen.style.setProperty("--shot-bg", `url("${src}")`);
    els.shot.classList.remove("empty");
    els.shot.classList.remove("swap");
    void els.shot.offsetWidth;
    els.shot.classList.add("swap");
    els.screen.classList.add("has-shot");
    els.expand.hidden = false;
    lastShotTag = tag || lastShotTag;
    if (tag) els.shottag.textContent = tag;
    if (!els.shotView.hidden) {
      els.shotViewImg.src = src;
      els.shotCap.textContent = lastShotTag;
    }
  };
  pre.onerror = () => toast("截图加载失败", true);
  pre.src = src;
  lastShotTag = tag || lastShotTag;
  if (tag) els.shottag.textContent = tag;
}

async function fetchShot(tag) {
  if (shotInFlight) return false;
  shotInFlight = true;
  try {
    const r = await api("/api/screenshot");
    if (!r.ok) return false;
    const blob = await r.blob();
    if (shotUrl) URL.revokeObjectURL(shotUrl);
    shotUrl = URL.createObjectURL(blob);
    setShot(shotUrl, tag);
    return true;
  } catch {
    return false;
  } finally {
    shotInFlight = false;
  }
}

async function manualShot(btn) {
  if (btn?.disabled) return;
  if (shotInFlight) { toast("截图正在刷新，稍等一下"); return; }
  const buttons = [els.shotBtn, els.shotDock];
  buttons.forEach((b) => { if (b) { b.disabled = true; b.classList.add("is-busy"); } });
  const ok = await fetchShot("手动刷新 " + new Date().toLocaleTimeString());
  if (!ok) toast("截图失败", true);
  buttons.forEach((b) => { if (b) { b.disabled = false; b.classList.remove("is-busy"); } });
}

function shotSchedule() {
  clearTimeout(shotTimer);
  if (shotGap <= 0) return;
  shotTimer = setTimeout(async () => {
    if (visible && lastConnected && !wasRunning && !startingRun) {
      await fetchShot("自动刷新 " + new Date().toLocaleTimeString());
    }
    shotSchedule();
  }, shotGap * 1000);
}

function shotStateTick() {
  let text;
  let on = false;
  if (wasRunning) {
    text = "运行中暂停";
  } else if (!lastConnected) {
    text = "等待设备";
  } else if (!visible) {
    text = "后台暂停";
  } else if (shotGap > 0) {
    text = "刷新中";
    on = true;
  } else {
    text = "已暂停";
  }
  if (els.shotState.textContent !== text) els.shotState.textContent = text;
  els.shotState.classList.toggle("on", on);
}

function openLightbox() {
  if (!els.screen.classList.contains("has-shot")) {
    toast("还没有截图，先刷新一次吧");
    return;
  }
  els.shotViewImg.src = els.shot.src;
  els.shotCap.textContent = lastShotTag || "";
  els.shotView.hidden = false;
  void els.shotView.offsetWidth;
  els.shotView.classList.add("show");
  document.body.classList.add("lightbox-open");
}
function closeLightbox() {
  if (els.shotView.hidden) return;
  els.shotView.classList.remove("show");
  document.body.classList.remove("lightbox-open");
  setTimeout(() => {
    if (!els.shotView.classList.contains("show")) els.shotView.hidden = true;
  }, 270);
}

/* ── 主题 ───────────────────────────────────────────────────────── */
function applyTheme(theme, persist = true) {
  const t = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = t;
  if (persist) writeText(STORE.theme, t);
  els.themeToggle.setAttribute("aria-pressed", String(t === "light"));
  els.themeToggle.title = t === "light" ? "切换到深色主题" : "切换到浅色主题";
  els.themeColor?.setAttribute("content", t === "light" ? "#f2ebdd" : "#080b10");
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.classList.add("theme-switching");
  applyTheme(next);
  clearTimeout(themeTimer);
  themeTimer = setTimeout(() => {
    document.documentElement.classList.remove("theme-switching");
  }, 420);
}

/* ── 目录抽屉 ───────────────────────────────────────────────────── */
function openCatalog() {
  if (!mqMobile.matches || catalogOpen) return;
  catalogOpen = true;
  els.catalog.classList.add("open");
  els.scrim.hidden = false;
  requestAnimationFrame(() => els.scrim.classList.add("show"));
  document.body.classList.add("drawer-open");
}
function closeCatalog() {
  if (!catalogOpen) return;
  catalogOpen = false;
  els.catalog.classList.remove("open");
  els.scrim.classList.remove("show");
  document.body.classList.remove("drawer-open");
  setTimeout(() => {
    if (!catalogOpen) els.scrim.hidden = true;
  }, 300);
}
function openSearch() {
  if (mqMobile.matches) openCatalog();
  setTimeout(() => {
    els.search.focus();
    els.search.select();
  }, mqMobile.matches ? 90 : 0);
}
function cycleScenario(dir) {
  if (isBusy()) return;
  const list = currentVisible();
  if (!list.length) return;
  let idx = selected ? list.findIndex((s) => s.id === selected.id) : -1;
  if (idx === -1) idx = dir > 0 ? -1 : 0;
  const next = list[(idx + dir + list.length) % list.length];
  selectScenario(next.id);
}

/* ── 加载场景 ───────────────────────────────────────────────────── */
async function loadScenarios() {
  renderSkeleton();
  try {
    const data = await api("/api/scenarios");
    scenarios = Array.isArray(data.scenarios) ? data.scenarios : [];
  } catch {
    renderLoadError("连不上本地服务，请确认 python main.py 仍在运行。");
    toast("读取场景列表失败", true);
    return;
  }
  if (!scenarios.length) {
    renderLoadError("服务没有返回任何场景。");
    return;
  }

  buildGroups();
  if (activeFilter !== "all" && !groups.some((g) => g.name === activeFilter)) {
    activeFilter = "all";
  }
  recent = recent.filter((id) => scenarios.some((s) => s.id === id));
  writeJSON(STORE.recent, recent);
  renderFilters();

  const saved = readText(STORE.last);
  const pick = scenarios.find((s) => s.id === saved) || scenarios[0];
  renderCatalog();
  selectScenario(pick.id, { silent: true, scroll: false });
}

/* ── 交互绑定 ───────────────────────────────────────────────────── */
function bind() {
  /* 场景卡片 / 分组折叠 */
  els.cards.addEventListener("click", (e) => {
    const head = e.target.closest(".group-head");
    if (head) {
      const sec = head.closest(".group");
      const closed = sec.classList.toggle("closed");
      head.setAttribute("aria-expanded", String(!closed));
      if (!query.trim() && activeFilter === "all") {
        const name = sec.dataset.group;
        if (closed) collapsed.add(name);
        else collapsed.delete(name);
        writeJSON(STORE.collapsed, [...collapsed]);
      }
      return;
    }
    const card = e.target.closest(".card");
    if (card) trySelect(card.dataset.id);
  });

  /* 筛选 */
  els.filters.addEventListener("click", (e) => {
    const btn = e.target.closest(".filter");
    if (!btn) return;
    activeFilter = btn.dataset.group;
    $$(".filter", els.filters).forEach((b) => {
      const on = b === btn;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    renderCatalog();
    els.catalogScroll.scrollTop = 0;
  });

  /* 搜索 */
  els.search.addEventListener("input", () => {
    query = els.search.value;
    els.searchWrap.classList.toggle("has-value", Boolean(query));
    els.searchClear.hidden = !query;
    renderCatalog();
    els.catalogScroll.scrollTop = 0;
  });
  els.searchClear.addEventListener("click", () => {
    query = "";
    els.search.value = "";
    els.searchWrap.classList.remove("has-value");
    els.searchClear.hidden = true;
    renderCatalog();
    els.catalogScroll.scrollTop = 0;
    els.search.focus();
  });
  els.btnClearFilter.addEventListener("click", () => {
    query = "";
    activeFilter = "all";
    els.search.value = "";
    els.searchWrap.classList.remove("has-value");
    els.searchClear.hidden = true;
    $$(".filter", els.filters).forEach((b) => {
      const on = b.dataset.group === "all";
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    renderCatalog();
    els.catalogScroll.scrollTop = 0;
  });

  /* 运行 & 控制 */
  els.run.addEventListener("click", () => runScenario());
  els.btnPause.addEventListener("click", pauseOrResume);
  els.btnStop.addEventListener("click", () => showModal(els.stopModal, els.btnStopNo));

  /* 参数 */
  els.params.addEventListener("input", (e) => {
    if (!(e.target instanceof HTMLInputElement)) return;
    renderSpec();
    e.target.classList.remove("pop");
    void e.target.offsetWidth;
    e.target.classList.add("pop");
  });
  els.btnReset.addEventListener("click", () => {
    if (!selected) return;
    renderParams();
    renderSpec();
    toast("已恢复默认参数");
  });

  /* 确认 / 询问 / 重试 / 停止 */
  els.btnSuccess.addEventListener("click", () => confirmAnswer(true));
  els.btnFail.addEventListener("click", () => confirmAnswer(false));
  els.btnAskYes.addEventListener("click", () => askAnswer(true));
  els.btnAskNo.addEventListener("click", () => askAnswer(false));
  els.btnRetryYes.addEventListener("click", () => {
    hideModal(els.retry);
    appendLine("detail", "用户选择重新触发：目标日期平移 +1 个月");
    runScenario({ offset_months: 1, retry: 1 });
  });
  els.btnRetryNo.addEventListener("click", failSettle);
  els.btnStopYes.addEventListener("click", stopRun);
  els.btnStopNo.addEventListener("click", () => hideModal(els.stopModal));

  /* 截图 */
  els.shotBtn.addEventListener("click", () => manualShot(els.shotBtn));
  els.shotDock.addEventListener("click", () => manualShot(els.shotDock));
  els.screen.addEventListener("click", (e) => {
    if (e.target.closest(".expand-btn")) return;
    openLightbox();
  });
  els.expand.addEventListener("click", (e) => {
    e.stopPropagation();
    openLightbox();
  });
  els.btnCloseShot.addEventListener("click", closeLightbox);
  els.shotView.addEventListener("click", (e) => {
    if (e.target === els.shotView) closeLightbox();
  });
  els.screen.tabIndex = 0;
  els.screen.setAttribute("role", "button");
  els.screen.setAttribute("aria-label", "查看手机截图大图");
  els.screen.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openLightbox();
    }
  });

  /* 截图刷新间隔 */
  els.shotGap.value = String(shotGap);
  els.shotGap.addEventListener("change", () => {
    let v = Number(els.shotGap.value);
    if (!Number.isFinite(v)) v = 5;
    v = Math.min(60, Math.max(1, Math.round(v)));
    els.shotGap.value = String(v);
    shotGap = v;
    writeText(STORE.shotGap, String(v));
    shotStateTick();
    shotSchedule();
  });
  els.shotGap.addEventListener("keydown", (e) => {
    if (e.key === "Enter") els.shotGap.blur();
  });

  /* 设备 */
  els.devstatus.addEventListener("click", () => {
    lastConnected = null;
    toast("正在重新检测设备…");
    refreshStatus();
  });
  els.scrcpy.addEventListener("click", async () => {
    try {
      const r = await api("/api/scrcpy", { method: "POST" });
      if (r.error) toast(r.error, true);
      else toast("已启动 scrcpy");
    } catch {
      toast("启动 scrcpy 失败：本地服务无响应", true);
    }
  });

  /* 日志 */
  els.btnClearLog.addEventListener("click", clearLog);

  /* 主题 */
  els.themeToggle.addEventListener("click", toggleTheme);

  /* 抽屉 */
  els.btnCatalog.addEventListener("click", () => {
    if (catalogOpen) closeCatalog();
    else openCatalog();
  });
  els.btnCloseCatalog.addEventListener("click", closeCatalog);
  els.scrim.addEventListener("click", closeCatalog);
  mqMobile.addEventListener("change", (e) => {
    if (!e.matches) closeCatalog();
  });

  /* 弹层背景关闭（仅可关闭的停止确认） */
  $$(".modal").forEach((m) => {
    m.addEventListener("click", (e) => {
      if (e.target === m && m.dataset.dismissible === "true") hideModal(m);
    });
  });

  /* 涟漪 */
  document.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const el = e.target.closest(".commit,.vbtn,.btn,.filter,.icon-btn");
    if (!el || el.disabled) return;
    const r = document.createElement("span");
    r.className = "ripple";
    const rect = el.getBoundingClientRect();
    const d = Math.max(rect.width, rect.height) * 2;
    r.style.width = r.style.height = d + "px";
    r.style.left = (e.clientX - rect.left - d / 2) + "px";
    r.style.top = (e.clientY - rect.top - d / 2) + "px";
    el.appendChild(r);
    r.addEventListener("animationend", () => r.remove());
  });

  /* 键盘快捷键 */
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    const typing = t && (
      t.tagName === "INPUT" || t.tagName === "TEXTAREA" ||
      t.tagName === "SELECT" || t.isContentEditable
    );
    const meta = e.ctrlKey || e.metaKey;

    if (meta && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      openSearch();
      return;
    }
    if (meta && e.key === "Enter") {
      e.preventDefault();
      runScenario();
      return;
    }
    if (e.key === "Escape") {
      if (!els.shotView.hidden) { closeLightbox(); return; }
      if (!els.stopModal.hidden) { hideModal(els.stopModal); return; }
      if (catalogOpen) { closeCatalog(); return; }
      if (query) {
        query = "";
        els.search.value = "";
        els.searchWrap.classList.remove("has-value");
        els.searchClear.hidden = true;
        renderCatalog();
        els.search.blur();
      }
      return;
    }
    if (e.key === "/" && !typing && !meta) {
      e.preventDefault();
      openSearch();
      return;
    }
    if (typing && t !== els.search) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      cycleScenario(e.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (t === els.search && e.key === "Enter") {
      e.preventDefault();
      const list = currentVisible();
      if (list.length) selectScenario(list[0].id);
    }
  });

  /* 切后台暂停轮询 / 截图 */
  document.addEventListener("visibilitychange", () => {
    visible = !document.hidden;
    shotSchedule();
    shotStateTick();
    if (visible) {
      poll();
      refreshStatus();
    }
  });
}

/* ── 定时轮询 ───────────────────────────────────────────────────── */
async function loop() {
  if (visible) await poll();
}
async function statusLoop() {
  if (visible) await refreshStatus();
}
let statusTimer = null;
function statusSchedule() {
  clearTimeout(statusTimer);
  statusTimer = setTimeout(async () => {
    await statusLoop();
    statusSchedule();
  }, lastConnected ? 5000 : 3000);
}

/* ── 启动 ───────────────────────────────────────────────────────── */
applyTheme(document.documentElement.dataset.theme || "dark", false);
bind();
refreshStatus();
shotStateTick();
shotSchedule();
statusSchedule();
/* 页面一打开就尝试抓一帧（状态接口有时要等几秒，别让画面空着） */
setTimeout(() => {
  if (visible && !wasRunning && !startingRun && !els.screen.classList.contains("has-shot")) {
    fetchShot("初始画面 " + new Date().toLocaleTimeString());
  }
}, 1200);
loadScenarios().catch((err) => {
  console.error(err);
  toast("界面初始化失败，请刷新页面", true);
}).finally(() => {
  poll();
  setInterval(loop, 600);
});
