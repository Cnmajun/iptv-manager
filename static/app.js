/* IPTV Manager 前端 */
const $ = (id) => document.getElementById(id);
const api = async (method, path, body) => {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) { const t = await r.text(); throw new Error(t || r.statusText); }
  return r.json();
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const copyText = (t) => { navigator.clipboard.writeText(t); alert("已复制"); };

let curPage = 1, selected = new Set(), cats = [], sources = [];

/* ---- tabs ---- */
document.querySelectorAll(".tab").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  document.querySelectorAll(".tabpane").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  $("tab-" + b.dataset.tab).classList.add("active");
  if (b.dataset.tab === "dupes") loadDupes();
  if (b.dataset.tab === "sources") loadSources();
  if (b.dataset.tab === "playlists") loadPlaylists();
  if (b.dataset.tab === "channels") { loadCats(); loadChannels(1); }
});

/* ---- stats ---- */
async function loadStats() {
  const s = await api("GET", "/api/stats");
  $("stats").textContent = `频道 ${s.channels}（启用 ${s.enabled}）· 订阅源 ${s.sources} · 输出订阅 ${s.playlists}`;
}

/* ---- 频道 ---- */
let debT;
function debouncedLoad() { clearTimeout(debT); debT = setTimeout(() => loadChannels(1), 400); }
function page(d) { loadChannels(curPage + d); }

async function loadCats() {
  cats = await api("GET", "/api/categories");
  const opts = ['<option value="">全部分类</option>'].concat(
    cats.map((c) => `<option value="${esc(c.name)}">${esc(c.name)} (${c.count})</option>`));
  $("fCat").innerHTML = opts.join("");
  $("adhocCat").innerHTML = opts.join("");
  $("plCats").innerHTML = cats.map((c) =>
    `<label><input type="checkbox" value="${esc(c.name)}"> ${esc(c.name)}</label>`).join("");
}
async function loadSourcesInto(sel) {
  sources = await api("GET", "/api/sources");
  $(sel).innerHTML = '<option value="0">全部来源</option>' + sources.map((s) =>
    `<option value="${s.id}">${esc(s.name)}</option>`).join("");
}

async function loadChannels(p) {
  curPage = Math.max(1, p);
  const q = new URLSearchParams({
    search: $("q").value, category: $("fCat").value, source_id: $("fSrc").value,
    enabled: $("fEn").value, page, per_page: 50,
  });
  const d = await api("GET", "/api/channels?" + q);
  selected = new Set(); updateBatchBar();
  $("chBody").innerHTML = d.items.map((c) => `
    <tr class="${c.enabled ? "" : "disabled"}">
      <td><input type="checkbox" data-id="${c.id}" onchange="selOne(${c.id}, this.checked)"></td>
      <td><input class="inline-edit" value="${esc(c.name)}"
           onchange="patchChannel(${c.id}, {name: this.value})" title="原名：${esc(c.orig_name)}"></td>
      <td><input class="inline-edit" style="width:100px" value="${esc(c.category)}"
           onchange="patchChannel(${c.id}, {category: this.value})"></td>
      <td>${esc(c.source_name)}</td>
      <td><input type="checkbox" ${c.enabled ? "checked" : ""}
           onchange="patchChannel(${c.id}, {enabled: this.checked})" title="启用/禁用"></td>
      <td><button class="ghost" onclick="delChannel(${c.id})">删除</button></td>
    </tr>`).join("");
  const pages = Math.max(1, Math.ceil(d.total / d.per_page));
  $("pageInfo").textContent = `第 ${curPage} / ${pages} 页，共 ${d.total} 个`;
  $("selAll").checked = false;
  loadStats();
}
function selOne(id, on) { on ? selected.add(id) : selected.delete(id); updateBatchBar(); }
function toggleAll(on) {
  document.querySelectorAll("#chBody input[type=checkbox][data-id]").forEach((cb) => {
    cb.checked = on; selOne(+cb.dataset.id, on);
  });
}
function updateBatchBar() {
  $("batchBar").classList.toggle("hidden", selected.size === 0);
  $("selCount").textContent = selected.size;
}
async function patchChannel(id, patch) {
  await api("PUT", `/api/channels/${id}`, patch);
  loadChannels(curPage);
}
async function delChannel(id) {
  if (!confirm("删除这个频道？")) return;
  await api("DELETE", `/api/channels/${id}`);
  loadChannels(curPage);
}
async function batchOp(op) {
  const ids = [...selected];
  if (op === "delete" && !confirm(`删除选中的 ${ids.length} 个频道？`)) return;
  if (op === "merge" && !confirm(`把选中的 ${ids.length} 个频道合并为 1 个（保留 ID 最小者）？`)) return;
  await api("POST", "/api/channels/batch", { ids, op });
  loadChannels(curPage);
}
async function batchSetCat() {
  const cat = prompt("归类到（输入分类名）：", $("fCat").value || "");
  if (cat === null) return;
  await api("POST", "/api/channels/batch", { ids: [...selected], op: "set_category", category: cat });
  loadCats(); loadChannels(curPage);
}

/* ---- 同名合并 ---- */
async function loadDupes() {
  const d = await api("GET", "/api/duplicates");
  $("dupeBadge").textContent = d.total_groups || "";
  $("dupeList").innerHTML = d.groups.length ? d.groups.map((g, i) => `
    <div class="dupe-group">
      <h4>${esc(g.channels[0].name)} <small style="color:#888">（${g.count} 个重复）</small></h4>
      ${g.channels.map((c) => `
        <label><input type="checkbox" data-g="${i}" value="${c.id}" checked>
        [${esc(c.category)}] ${esc(c.name)} <small style="color:#888">${esc(c.source_name)}${c.enabled ? "" : "（已禁用）"}</small></label>`).join("")}
      <button onclick="mergeGroup(${i})">合并选中项</button>
    </div>`).join("") : '<p class="hint">没有发现重复频道 🎉</p>';
}
async function mergeGroup(i) {
  const ids = [...document.querySelectorAll(`input[data-g="${i}"]:checked`)].map((x) => +x.value);
  if (ids.length < 2) { alert("至少勾选 2 个才能合并"); return; }
  if (!confirm(`合并这 ${ids.length} 个为 1 个（保留 ID 最小者）？`)) return;
  await api("POST", "/api/channels/batch", { ids, op: "merge" });
  loadDupes(); loadStats();
}

/* ---- 订阅源 ---- */
async function addSource() {
  const name = $("srcName").value.trim(), url = $("srcUrl").value.trim();
  const interval_hours = +$("srcInterval").value || 12;
  if (!name || !url) { alert("名称和链接都要填"); return; }
  const r = await api("POST", "/api/sources", { name, url, interval_hours });
  $("srcName").value = ""; $("srcUrl").value = "";
  await api("POST", `/api/sources/${r.id}/refresh`).catch((e) => alert("添加成功，但首次抓取失败：" + e.message));
  loadSources(); loadStats(); loadSourcesInto("fSrc");
}
async function loadSources() {
  const list = await api("GET", "/api/sources");
  $("srcList").innerHTML = list.map((s) => `
    <div class="srcrow">
      <b>${esc(s.name)}</b>
      <span class="meta">${esc(s.url.slice(0, 60))}… · 每 ${s.interval_hours}h 更新 ·
        ${s.last_status === "ok" ? "✅ " + esc(s.last_message || "") :
          s.last_status === "error" ? "❌ " + esc(s.last_message || "") : "⏳ 未抓取"}</span>
      <span style="flex:1"></span>
      <button class="ghost" onclick="refreshSource(${s.id})">立即更新</button>
      <button class="ghost" onclick="toggleSource(${s.id}, ${!s.enabled})">${s.enabled ? "暂停" : "启用"}</button>
      <button class="danger" onclick="delSource(${s.id})">删除</button>
    </div>`).join("") || '<p class="hint">还没有订阅源，先添加一个吧</p>';
}
async function refreshSource(id) {
  const r = await api("POST", `/api/sources/${id}/refresh`).catch((e) => ({ error: e.message }));
  alert(r.error ? "抓取失败：" + r.error : `抓取完成：新增 ${r.added}，更新 ${r.updated}`);
  loadSources(); loadStats();
}
async function toggleSource(id, enabled) {
  const s = sources.find((x) => x.id === id);
  await api("PUT", `/api/sources/${id}`, { name: s.name, url: s.url, enabled, interval_hours: s.interval_hours });
  loadSources();
}
async function delSource(id) {
  if (!confirm("删除该订阅源及其全部频道？")) return;
  await api("DELETE", `/api/sources/${id}`);
  loadSources(); loadStats(); loadSourcesInto("fSrc"); loadCats();
}

/* ---- 输出订阅 ---- */
function baseUrl() { return location.origin; }
async function addPlaylist() {
  const name = $("plName").value.trim();
  if (!name) { alert("起个名字"); return; }
  const categories = [...document.querySelectorAll("#plCats input:checked")].map((x) => x.value);
  const search = $("plSearch").value.trim();
  const include_backups = $("plBackups").checked;
  await api("POST", "/api/playlists", { name, categories, search, include_backups });
  $("plName").value = ""; $("plSearch").value = "";
  loadPlaylists(); loadStats();
}
async function loadPlaylists() {
  const list = await api("GET", "/api/playlists");
  $("plList").innerHTML = list.map((p) => {
    const url = `${baseUrl()}/p/${p.id}.m3u`;
    const f = p.filters;
    const desc = [f.categories?.length ? "分类:" + f.categories.join(",") : null,
      f.search ? "关键词:" + f.search : null,
      f.include_backups ? "含备用源" : null].filter(Boolean).join("；") || "全部频道";
    return `<div class="plrow"><b>${esc(p.name)}</b><small class="hint">${esc(desc)}</small>
      <code>${esc(url)}</code>
      <button onclick="copyText('${url}')">复制</button>
      <button class="danger" onclick="delPlaylist(${p.id})">删除</button></div>`;
  }).join("") || '<p class="hint">还没有自定义输出，先创建一个吧</p>';
  updateAdhoc();
}
async function delPlaylist(id) {
  if (!confirm("删除这个输出订阅？")) return;
  await api("DELETE", `/api/playlists/${id}`);
  loadPlaylists(); loadStats();
}
function updateAdhoc() {
  const cat = $("adhocCat").value;
  $("adhocUrl").textContent = `${baseUrl()}/playlist.m3u` + (cat ? `?category=${encodeURIComponent(cat)}` : "");
  $("lanHint").textContent = location.hostname + (location.port ? ":" + location.port : "");
}

/* ---- init ---- */
(async () => {
  await loadStats(); await loadCats(); await loadSourcesInto("fSrc");
  await loadChannels(1); updateAdhoc();
})();
