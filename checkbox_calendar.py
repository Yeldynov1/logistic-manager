"""HTML-календар архіву Checkbox."""
import json


def calendar_html(iso_date: str, days_with_data: list) -> str:
    days_json = json.dumps(days_with_data)
    tpl = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fff; }
.wrap { max-width: 400px; }
.lbl { font-size: 13px; color: #00a8c8; margin-bottom: 6px; font-weight: 500; }
.field { border: 2px solid #2ec5e8; border-radius: 10px; padding: 10px 14px; font-size: 15px; color: #333; background: #fff; }
.banner { background: linear-gradient(135deg, #2ec5e8 0%, #1eb8dd 100%); color: #fff; border-radius: 10px 10px 0 0; padding: 14px 16px 12px; margin-top: 8px; }
.banner .yr { font-size: 13px; margin-bottom: 4px; }
.banner .rg { font-size: 20px; font-weight: 700; }
.cal { border: 1px solid #e8e8e8; border-top: none; border-radius: 0 0 10px 10px; padding: 12px 14px 10px; }
.nav { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.nav button { border: none; background: none; font-size: 22px; color: #888; cursor: pointer; padding: 4px 10px; }
.nav .title { font-size: 15px; font-weight: 600; color: #333; }
.wdays { display: grid; grid-template-columns: repeat(7, 1fr); text-align: center; font-size: 12px; color: #999; margin-bottom: 6px; }
.days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
.day { aspect-ratio: 1; display: flex; align-items: center; justify-content: center; font-size: 14px; border-radius: 50%; cursor: pointer; border: none; background: none; }
.day:hover:not(.empty):not(.muted) { background: #e8f7fc; }
.day.sel { background: #2ec5e8 !important; color: #fff; font-weight: 600; }
.day.muted { color: #ccc; cursor: default; }
.day.empty { visibility: hidden; }
.foot { display: flex; gap: 10px; align-items: center; margin-top: 12px; padding-top: 10px; border-top: 1px solid #eee; }
.foot select { flex: 1; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
.foot .ok { padding: 10px 22px; background: #2ec5e8; color: #fff; border: none; border-radius: 20px; font-size: 14px; font-weight: 600; cursor: pointer; }
.foot .ok:hover { background: #1eb8dd; }
</style>
</head><body>
<div class="wrap">
  <div class="lbl">Дата фіскалізації</div>
  <div id="field" class="field"></div>
  <div class="banner"><div id="yr" class="yr"></div><div id="rg" class="rg"></div></div>
  <div class="cal">
    <div class="nav"><button type="button" id="prev">&#8249;</button><div id="mtitle" class="title"></div><button type="button" id="next">&#8250;</button></div>
    <div class="wdays"><span>П</span><span>В</span><span>С</span><span>Ч</span><span>П</span><span>С</span><span>Н</span></div>
    <div id="days" class="days"></div>
    <div class="foot"><select id="period"><option value="">Обрати період</option><option value="today">Сьогодні</option><option value="yesterday">Вчора</option></select><button type="button" class="ok" id="apply">Обрати</button></div>
  </div>
</div>
<script>
(function() {
  const MONTHS = ["січень","лютий","березень","квітень","травень","червень","липень","серпень","вересень","жовтень","листопад","грудень"];
  const daysWithData = new Set(__DAYS_JSON__);
  let cur = new Date("__ISO_DATE__T12:00:00");
  let sel = new Date("__ISO_DATE__T12:00:00");
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function fmt(d) { return pad(d.getDate()) + "." + pad(d.getMonth()+1) + "." + d.getFullYear(); }
  function iso(d) { return d.getFullYear() + "-" + pad(d.getMonth()+1) + "-" + pad(d.getDate()); }
  function hasData(d) { return daysWithData.has(iso(d)); }
  function refreshBanner() {
    const s = fmt(sel);
    document.getElementById("field").textContent = s + " - " + s;
    document.getElementById("yr").textContent = sel.getFullYear();
    document.getElementById("rg").textContent = s + " - " + s;
    document.getElementById("mtitle").textContent = MONTHS[cur.getMonth()] + " " + cur.getFullYear() + " р.";
  }
  function renderDays() {
    const box = document.getElementById("days");
    box.innerHTML = "";
    const y = cur.getFullYear(), m = cur.getMonth();
    const first = new Date(y, m, 1);
    let start = first.getDay(); if (start === 0) start = 7; start -= 1;
    const dim = new Date(y, m + 1, 0).getDate();
    for (let i = 0; i < start; i++) { const e = document.createElement("button"); e.className = "day empty"; e.disabled = true; box.appendChild(e); }
    for (let d = 1; d <= dim; d++) {
      const dt = new Date(y, m, d, 12, 0, 0);
      const b = document.createElement("button"); b.type = "button"; b.className = "day"; b.textContent = d;
      if (iso(dt) === iso(sel)) b.classList.add("sel");
      if (!hasData(dt) && iso(dt) !== iso(sel)) b.classList.add("muted");
      b.onclick = () => { sel = dt; refreshBanner(); renderDays(); };
      box.appendChild(b);
    }
    refreshBanner();
  }
  document.getElementById("prev").onclick = () => { cur = new Date(cur.getFullYear(), cur.getMonth() - 1, 1); renderDays(); };
  document.getElementById("next").onclick = () => { cur = new Date(cur.getFullYear(), cur.getMonth() + 1, 1); renderDays(); };
  document.getElementById("period").onchange = function() {
    const v = this.value; const t = new Date(); t.setHours(12,0,0,0);
    if (v === "today") sel = t; else if (v === "yesterday") sel = new Date(t.getFullYear(), t.getMonth(), t.getDate() - 1, 12, 0, 0);
    cur = new Date(sel.getFullYear(), sel.getMonth(), 1); this.value = ""; renderDays();
  };
  document.getElementById("apply").onclick = function() {
    try { const u = new URL(window.parent.location.href); u.searchParams.set("chk_arch_day", iso(sel)); window.parent.location.href = u.toString(); }
    catch (e) { alert(iso(sel)); }
  };
  renderDays();
})();
</script>
</body></html>"""
    return tpl.replace("__DAYS_JSON__", days_json).replace("__ISO_DATE__", iso_date)
