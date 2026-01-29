const $ = (id) => document.getElementById(id);

let posts = [];
let currentPost = null;

function norm(u){ return (u||"").replace(/\?.*$/,""); }
function getId(u){
  const m = norm(u).match(/\/detail\/(\d+)/);
  return m ? m[1] : "";
}

function sortNew(a,b){
  return (b.datetime||"").localeCompare(a.datetime||"");
}

function escapeHtml(s){
  return (s??"").toString()
    .replaceAll("&","&amp;").replaceAll("<","&lt;")
    .replaceAll(">","&gt;").replaceAll('"',"&quot;");
}

function formatDateParts(dt){
  const m = (dt||"").match(/(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})/);
  if(!m) return {ym:"----/--", dd:"--", dow:"---", dt:"----"};
  const [_, y, mo, d, hh, mm] = m;
  const date = new Date(`${y}-${mo}-${d}T${hh}:${mm}:00+09:00`);
  const dows = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  return { ym:`${y}/${mo}`, dd:`${d}`, dow:dows[date.getDay()], dt:`${y}.${mo}.${d} ${hh}:${mm}` };
}

function filter(q){
  q = (q||"").trim().toLowerCase();
  if(!q) return posts;
  return posts.filter(p=>{
    const id = (p.id || getId(p.url)).toLowerCase();
    const t = (p.title||"").toLowerCase();
    return t.includes(q) || id.includes(q);
  });
}

function renderList(items){
  const list = $("list");
  list.innerHTML = "";
  items.forEach(p=>{
    const id = p.id || getId(p.url);
    const div = document.createElement("div");
    div.className = "item" + (currentPost && currentPost.id===id ? " active":"");
    div.innerHTML = `
      <div class="t">${escapeHtml(p.title||"no-title")}</div>
      <div class="d">${escapeHtml(p.datetime||"unknown")} / ${escapeHtml(id)}</div>
    `;
    div.onclick = ()=>openPost(p);
    list.appendChild(div);
  });
}

async function openPost(p){
  const id = p.id || getId(p.url);
  currentPost = { id, url: p.url };

  renderList(filter($("q").value));

  const parts = formatDateParts(p.datetime||"");
  $("ym").textContent = parts.ym;
  $("dd").textContent = parts.dd;
  $("dow").textContent = parts.dow;
  $("dt").textContent = parts.dt;
  $("title").textContent = p.title || "no-title";

  // srcを開くボタン
  $("openSrc").onclick = ()=> window.open(p.url, "_blank");

  // page.html を表示（posts/.. にある）
  const pagePath = `../${p.local_dir}/page.html`;
  const html = await fetch(pagePath).then(r=>r.text());

  $("content").innerHTML = html;
}

async function init(){
  posts = await fetch("../index/posts.json").then(r=>r.json());
  posts.sort(sortNew);
  renderList(posts);

  $("q").addEventListener("input",(e)=>{
    renderList(filter(e.target.value));
  });

  // 最新を自動で開きたいなら↓
  // if(posts.length) openPost(posts[0]);
}
init();
