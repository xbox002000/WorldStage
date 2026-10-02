/* 導播室 — reads studio.json (channel/studio.py) and shows the day's episode, the producer's hand, the payoffs and the people.
   No dependencies. It only reads; "go on" asks the process that serves it to run the world one more day. */
(() => {
"use strict";

const INTENT = {
  orient: ["交代場景", "說清楚在哪裡、誰在場"], reveal: ["揭曉", "讓觀眾看見真相"], hide: ["藏起來", "只給動作，不給臉"],
  escalate: ["升高衝突", "壓力逼近"], reaction: ["反應", "看它落在對方身上"], payoff: ["兌現", "前面埋的東西在這裡落地"],
  misdirect: ["誤導", "讓觀眾懷疑錯的人"], foreshadow: ["伏筆", "東西留下了，沒人發現"], isolate: ["孤立", "讓他一個人面對"],
  connect: ["連結", "兩個人之間的溫度"], contrast: ["反差", "荒謬的東西說出了真話"], observe: ["旁觀", "靜靜看著"],
  setup: ["鋪陳", "事情從這裡開始"], face_slap: ["打臉", "看輕他的人親眼看見"], bystander_shock: ["眾人震驚", "全場安靜下來"],
  longing_glance: ["凝望", "一個停太久的眼神"], rival_standoff: ["對峙", "想要同一樣東西的人面對面"], confession: ["告白", "說出口了"],
  choice: ["抉擇", "做決定之前的一刻"], aftermath: ["餘波", "事後剩下的"], next_question: ["下一個問題", "他現在想要什麼"],
};
const STAGE = {
  daily: ["日常", "#9aa5b1"], anomaly: ["異常", "#5fa0c7"], doubt: ["懷疑", "#8c7fd1"], rising: ["升溫", "#d9ab2f"],
  conflict: ["衝突", "#e0762f"], choice: ["抉擇", "#a14ad1"], irreversible: ["不可逆", "#c4392f"], change: ["改變", "#2e8f5b"],
};
const KIND = { payoff: "爽點集", inner: "內在衝突集", thread: "故事線集" };
const STEP = {
  belittled: ["被看輕", "沒有人當眾看輕他的紀錄"], hidden_growth: ["暗中成長", "沒有他私下練功的紀錄"],
  gathering: ["公開場合", "沒有公開的場合"], reversal: ["反轉", ""], bystanders: ["旁觀者反應", "沒有旁觀者看見"],
  new_state: ["新的處境", "反轉之後沒有留下可以讀出來的改變"],
};
const STRATEGY = { off: "不製作", greedy: "標準製作人", portfolio: "作品組合製作人", lookahead: "會想像未來的製作人", matched: "隨機對照", blind: "盲選對照", aggressive: "不停手", unlimited: "不限預算" };
const REASON = {
  "a great deal has just happened": "剛剛發生太多事，先讓大家喘口氣",
  "no story is open that could use anything": "目前沒有哪個故事需要插手",
  "the world has what this story needs": "這個故事需要的條件世界都有了，不必插手",
  "supplied what the story lacked": "補上這個故事缺的條件",
  "nothing could be admitted": "想做的都被規則或預算擋下了",
  "imagined futures come out as well without it": "想像了幾種未來：不插手結果一樣好",
};
const LACK = { occasion: "公開的場合", challenger: "會挑戰他的對手", vacancy: "空出來的位子", strength: "實力還差一點", recovery: "有人受傷，要等" };
const STORY = { reversal: "逆襲", succession: "奪位", triangle: "三角關係" };
const ROLE = { doubter: "看輕者", rival: "對手", mentor: "伯樂", troublemaker: "搗亂者", suitor: "追求者" };
const STRENGTH = { cast_role: "soft", deliver_parcel: "soft", announce_visitor: "soft", announce_gathering: "medium", open_seat: "medium" };
const STRENGTH_ZH = { soft: "輕", medium: "中", hard: "重" };
const ICON = { announce_gathering: "🏟", deliver_parcel: "📜", open_seat: "🪑", cast_role: "🎭", announce_visitor: "🚪" };
const EMO = { happy: "開心", hurt: "受傷", angry: "生氣", calm: "平靜", uneasy: "不安", ashamed: "羞愧", embarrassed: "尷尬", scared: "害怕", relieved: "鬆一口氣", sad: "難過", proud: "得意", curious: "好奇", tired: "疲倦" };
const REL = { trust: ["信任", 1], affection: ["好感", 1], respect: ["尊重", 1], resentment: ["怨恨", -1], estimate: ["能力評價", 1], attraction: ["愛慕", 1], fear: ["恐懼", -1], rivalry: ["較勁", -1] };
const PAYOFF = { face_slap: "打臉", chosen: "被選中", succession: "奪得位子" };
const DEBT = { humiliation: "受挫", betrayal: "背叛與敵意", gap: "被低估", longing: "單戀", grudge: "怨恨" };
const PHASE = { calm: "平靜", warm: "升溫中", peak: "高峰" };

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => Math.round(x * 100);
const sgn = (x) => (x >= 0 ? "＋" : "−") + Math.abs(x).toFixed(2);
const emo = (e) => EMO[e] || e;
const hue = (name) => { let h = 0; for (const c of String(name)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };
const avatar = (name) => `<span class="av" style="background:hsl(${hue(name)} 45% 42%)" title="${esc(name)}">${esc(String(name).slice(-2))}</span>`;

let D = null;
const S = { day: 0, filter: "all", tab: "producer", person: null, scene: null, step: null, view: "story", frameReady: false, pending: null, tlPerson: null, tlHide: new Set() };

/* ---------- loading ---------- */
async function load() {
  if (window.STUDIO) return window.STUDIO;
  const r = await fetch("studio.json", { cache: "no-store" });
  return r.json();
}
function toast(msg) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.setAttribute("role", "status"); document.body.appendChild(t); Object.assign(t.style, { position: "fixed", left: "50%", bottom: "22px", transform: "translateX(-50%)", background: "var(--ink)", color: "var(--bg)", padding: "9px 16px", borderRadius: "10px", fontSize: "13px", zIndex: 9, maxWidth: "90vw" }); }
  t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => { t.hidden = true; }, 5200);
}

/* ---------- small helpers over the data ---------- */
const dayOf = (n) => D.days[n];
const kindOf = (d) => (d.episode ? d.episode.kind : "none");
const peak = (d) => (d.episode && d.episode.tension_curve.length ? Math.max(...d.episode.tension_curve) : 0.08);
const acted = (d) => d.producer.decisions.some((x) => x.action === "intervene");
const kept = (d) => d.producer.decisions.some((x) => x.action === "silence");
const allPayoffs = () => D.days.flatMap((d) => d.payoffs.map((p) => ({ ...p, day: d.day })));
const intentName = (k) => (INTENT[k] ? INTENT[k][0] : k);

function relChip(text) {
  const m = /^(.+?)>(.+?) (\w+) ([+-]\d+(?:\.\d+)?)$/.exec(text);
  if (!m) return `<span class="cg">${esc(text)}</span>`;
  const [, a, b, f, v] = m; const [zh, good] = REL[f] || [f, 1]; const n = parseFloat(v);
  return `<span class="cg ${n * good >= 0 ? "up" : "down"}" title="${esc(a)}對${esc(b)}的${zh}">${esc(a)}→${esc(b)} ${zh} ${sgn(n)}</span>`;
}
function stateChip(text) {
  if (text.startsWith("object")) return `<span class="cg">東西換了主人</span>`;
  if (text.startsWith("seat")) return `<span class="cg up">位子換人了</span>`;
  if (text.startsWith("skill")) return `<span class="cg up">功力變了</span>`;
  if (text.startsWith("role")) return `<span class="cg">被指派了角色</span>`;
  if (text.startsWith("goal")) return `<span class="cg feel">${esc(text.replace(/^goal\s*/, "目標 "))}</span>`;
  return `<span class="cg">${esc(text)}</span>`;
}

/* ---------- header ---------- */
function renderHeader() {
  const m = D.meta, t = D.totals || {};
  const chips = [
    ["世界", `${m.title || ""} 種子 ${m.seed}`.trim()], ["製作人", STRATEGY[m.strategy] || m.strategy], ["已走", `${m.days} 天`],
    ["爽點", `${t.count ?? 0} 個`], ["自己掙來", t.earned_share != null ? `${pct(t.earned_share)}%` : "—"],
  ];
  if (m.mind) chips.splice(2, 0, ["心智", `LLM ・ ${m.mind.model}`]);
  $("#chips").innerHTML = chips.map(([k, v]) => `<span class="chip"><span class="dim">${k}</span><b>${esc(v)}</b></span>`).join("");
  mindNote();
}
/* a world whose people have a mind (soul_lab.py): say what is being looked at. Nothing is added to any other world. */
function mindNote() {
  const m = D.meta.mind; let el = $("#mindNote");
  if (!m) { if (el) el.remove(); return; }
  if (!el) { el = document.createElement("p"); el.id = "mindNote"; el.className = "mindnote"; $("#top").insertAdjacentElement("afterend", el); }
  for (const id of ["#go1", "#go7"]) { const b = $(id); b.classList.add("ro"); b.title = "這個世界只能看，不能再走（點一下看原因）"; }
  el.innerHTML = `<span class="llm">LLM</span> 這個世界的人有 LLM 當心智。這一頁是把當初已經付費的答案（${m.answers} 筆）重播一遍：不連網、不花額度，重播出的 ${m.replay_events} 件事和當初留下的世界逐筆相同。標「LLM」的行動是他的心智決定的；<b>心聲</b>是他沒有說出口的想法。只能看，不能再走。`;
}
const minds = () => (D.minds && D.minds.items) || [];
const mindsOf = (day) => minds().filter((x) => x.day === day);

/* ---------- the season strip ---------- */
function renderStrip() {
  const el = $("#strip");
  el.innerHTML = D.days.map((d) => {
    const k = kindOf(d); const dim = S.filter !== "all" && S.filter !== k;
    const h = Math.round(6 + peak(d) * 56);
    return `<button class="day${dim ? " dim" : ""}" role="option" data-d="${d.day}" aria-selected="${d.day === S.day}" title="第 ${d.day + 1} 天：${esc(d.episode ? d.episode.core_question : "沒有集")}">
      <span class="col"><i class="${k}" style="height:${h}px"></i></span>
      <span class="n">${d.day + 1}</span>
      <span class="marks">${acted(d) ? '<span class="mk act" title="製作人出手"></span>' : kept(d) ? '<span class="mk still" title="製作人刻意不動"></span>' : ""}${d.payoffs.length ? '<span class="star" title="這天有爽點">★</span>' : ""}</span>
    </button>`;
  }).join("");
  const sel = $(`.day[data-d="${S.day}"]`, el);
  if (sel) el.scrollLeft = sel.offsetLeft - (el.clientWidth - sel.offsetWidth) / 2;   // the strip scrolls sideways; the page stays where it is
}

/* ---------- the episode ---------- */
function renderEpisode() {
  const d = dayOf(S.day); const ep = d.episode; const root = $("#episode");
  if (!ep) {
    root.innerHTML = `<div class="card ephead"><div class="kicker"><span class="badge">安靜的一天</span>第 ${d.day + 1} 天</div><div class="question">這天沒有值得說成一集的事</div><p class="dim" style="margin-top:8px">世界照常過日子，只是沒有哪件事夠格。看右邊「製作人」，它這天做了什麼。</p></div>${dayMinds(d)}`;
    return;
  }
  const filmed = ep.beats.filter((b) => b.shoot); const dropped = ep.beats.filter((b) => !b.shoot);
  const reveal = { irony: ["觀眾先知道", "yes"], mystery: ["觀眾跟著追", "yes"], plain: ["一般敘事", "no"] }[ep.reveal.strategy] || ["", "no"];
  const facts = [
    [ep.has_breath ? "有喘息" : "沒有喘息", ep.has_breath ? "yes" : "no", "張力有起伏，不是一路往上"],
    [reveal[0], reveal[1], "真相什麼時候到觀眾手上"],
    [ep.inner_conflict ? "有內在衝突" : "沒有內在衝突", ep.inner_conflict ? "hot" : "no", "有人做了違背自己在乎的事的選擇"],
    [ep.near_miss.length ? "差一點揭開" : "沒有差一點揭開", ep.near_miss.length ? "hot" : "no", "有人差一點就發現了真相"],
    [{ goal: "目標的問題", choice: "抉擇的問題", revelation: "揭曉的問題", open: "開放的問題" }[ep.question_type] || "", "no", "這個問題問的是：能不能得到、選哪一個、誰會發現"],
    [`${filmed.length} 場要拍・${dropped.length} 場不拍`, "no", "什麼都沒改變、或沒人在場的場景不拍"],
  ];
  const people = ep.people_names.map(avatar).join("");
  root.innerHTML = `
  <div class="card ephead ${ep.kind}">
    <div class="kicker"><span class="badge ${ep.kind}">${KIND[ep.kind]}</span><span>第 ${d.day + 1} 天</span><span class="who">${people}</span>${D.world3d ? `<button class="seek" data-play="1" title="在 3D 世界裡，依序看這一集的每一場">▶ 在現場播放這一集</button>` : ""}</div>
    <div class="question">${esc(ep.core_question)}</div>
    ${ep.ending_question ? `<div class="ending"><b>結尾留下</b>${esc(ep.ending_question)}</div>` : `<div class="ending"><b>結尾</b><span class="dim">這集把事情都收掉了，沒有留下問題</span></div>`}
    <div class="facts">${facts.filter(([t]) => t).map(([t, c, tip]) => `<span class="fact ${c}" title="${esc(tip)}">${esc(t)}</span>`).join("")}</div>
  </div>
  ${dayMinds(d)}
  ${ep.grammar.length ? `<div class="card block"><h3>爽文六步</h3><p class="note">亮起來的，是世界真的產生了的；虛線的，是世界沒有產生，這裡不會替它編。</p>
    <div class="steps">${ep.grammar.map((g, i) => `<button class="step${g.present ? "" : " miss"}" data-s="${i}" aria-expanded="${S.step === i}">
      <span class="no">第 ${i + 1} 步</span><div class="t">${STEP[g.step][0]}</div><div class="s">${g.present ? (g.event_ids.length ? `${g.event_ids.length} 件事` : "有") : "世界沒有產生"}</div></button>`).join("")}</div>
    <div class="stepdetail" id="stepdetail"></div></div>` : ""}
  <div class="card block"><h3>張力的起伏</h3><p class="note">每個點是一場要拍的戲。點一下，看那場戲的內容。</p>${chart(filmed)}</div>
  <div class="card block"><h3>這一集的場景</h3><p class="note">${filmed.length} 場，照發生的順序。每張卡片：這場戲是為了什麼、誰在場、改變了什麼。</p>
    <div class="scenes">${filmed.map((b, i) => sceneCard(b, i + 1)).join("")}</div>
    ${dropped.length ? `<details class="dropped"><summary>沒拍的 ${dropped.length} 場（什麼都沒改變，或沒人在場）</summary><ul>${dropped.map((b) => `<li>${esc((b.events[0] || {}).caption || "（沒有人在場的事）")}：${b.reason === "nothing changed" ? "什麼都沒改變" : b.reason === "no one on stage" ? "沒人在場" : esc(b.reason)}</li>`).join("")}</ul></details>` : ""}
  </div>`;
  if (S.step != null) showStep(S.step);
}

function chart(beats) {
  if (!beats.length) return `<div class="empty">這集沒有要拍的場景</div>`;
  const W = 640, H = 196, L = 34, R = 16, T = 14, B = 52, n = beats.length;
  const PAD = 34;   // room for the first and last label
  const x = (i) => (n === 1 ? (L + W - R) / 2 : L + PAD + (i * (W - L - R - 2 * PAD)) / (n - 1));
  const y = (t) => T + (1 - t) * (H - T - B);
  const pts = beats.map((b, i) => [x(i), y(b.tension), b]);
  const line = pts.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
  const area = `${line} L${pts[n - 1][0].toFixed(1)} ${H - B} L${pts[0][0].toFixed(1)} ${H - B} Z`;
  const grid = [0, 0.5, 1].map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${t === 0 ? "低" : t === 1 ? "高" : ""}</text>`).join("");
  const used = new Set(beats.map((b) => b.stage));
  const dots = pts.map(([px, py, b], i) => `<g><circle class="pt${S.scene === b.index ? " on" : ""}" data-b="${b.index}" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="9" fill="${STAGE[b.stage][1]}" tabindex="0" role="button" aria-label="第 ${i + 1} 場 ${intentName(b.intent)}"><title>第 ${i + 1} 場：${intentName(b.intent)}（${STAGE[b.stage][0]}）</title></circle>
    <text class="lbl" x="${px.toFixed(1)}" y="${H - B + 20}">${intentName(b.intent)}</text><text x="${px.toFixed(1)}" y="${H - B + 35}" text-anchor="middle">${i + 1}</text></g>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="這一集每場戲的張力">${grid}<path class="area" d="${area}"/><path class="line" d="${line}"/>${dots}</svg>
    <div class="legend">${[...used].map((s) => `<span><i style="background:${STAGE[s][1]}"></i>${STAGE[s][0]}</span>`).join("")}<span class="dim">（顏色是這場戲在故事階梯上的位置）</span></div>`;
}

/* the mind behind an action: what he said, what he thought and did not say, why he woke, where his choice stood among the rule agent's options */
function mindBlock(m, cap, id) {
  const idle = m.chose === "什麼都不做";
  const top = m.rank === 0 ? `規則最想做的，正是他選的${idle ? "（什麼都不做）" : ""}。`
    : `規則最想做的是「${esc(m.rule_top)}」，他選了「${esc(m.chose)}」（規則排第 ${m.rank + 1}，共 ${m.of} 個選項）。`;
  return `<details class="mind"${id != null ? ` id="mind${id}"` : ""}><summary><span class="llm" title="這個行動是角色的心智（LLM）決定的，不是規則">LLM</span>${cap ? `<span class="mcap">${esc(cap)}</span>` : ""}<span class="msay">他說：${esc(m.reason)}</span></summary>
    <div class="mbody">${m.inner ? `<div class="minner"><b>心裡想：</b>${esc(m.inner)}</div>` : `<div class="minner none">（沒有說不出口的想法）</div>`}
      ${m.wake && m.wake.length ? `<div class="mwhy"><b>為什麼醒來：</b>${m.wake.map(esc).join("；")}</div>` : ""}
      <div class="mtop">${top}</div></div></details>`;
}
function sceneMinds(b) {
  const ms = b.events.filter((e) => e.mind);
  return ms.map((e) => mindBlock(e.mind, b.events.length > 1 ? e.caption : "")).join("");
}
function dayMinds(d) {
  const list = mindsOf(d.day); if (!list.length) return "";
  return `<div class="card block minds"><h3><span class="llm">LLM</span> 這天誰動了心思（${list.length} 次）</h3><p class="note">他們每次「醒來」想了一下，才做了這件事。點開看他怎麼說、心裡怎麼想。沒有拍進場景的，也在這裡。</p>
    <div class="mlist">${list.map((m) => `<div class="mrow" id="mrow${m.n}"><div class="mhead">${avatar(m.name)}<b>${esc(m.name)}</b><span class="dim">${esc(m.clock)}</span>${m.beat != null ? `<button class="cg" data-scene="${m.beat}" title="這件事被拍進了這一集的一場戲">到那場戲</button>` : ""}${m.event != null ? seekBtn({ t: m.t, place_id: m.place_id }, m.person, "在現場看") : ""}</div>${mindBlock(m, "")}</div>`).join("")}</div></div>`;
}
function focusMind(n) {   // a mind from the people page: the scene that shows it, else its row in the day's list
  const m = minds().find((x) => x.n === n); if (!m) return;
  setView("story"); select(Math.max(0, Math.min(D.days.length - 1, m.day)), false);
  const el = m.beat != null && $(`#sc${m.beat}`) ? $(`#sc${m.beat}`) : $(`#mrow${m.n}`);
  if (m.beat != null && el) focusScene(m.beat); else if (el) { el.classList.add("on"); el.scrollIntoView({ behavior: "smooth", block: "center" }); setTimeout(() => el.classList.remove("on"), 2600); }
  const d = el && el.querySelector("details.mind"); if (d) d.open = true;
}

function sceneCard(b, n) {
  const [name, tip] = INTENT[b.intent] || [b.intent, ""]; const [stageName] = STAGE[b.stage];
  const c = b.checklist; const ev = b.events[0] || {};
  const caps = b.derived ? "在場的人看見了剛才的事，各有各的反應" : b.events.map((e) => e.caption).join("；");
  const changes = [
    ...Object.entries(c.emotion).map(([who, [a, z]]) => `<span class="cg feel">${esc(who)} ${emo(a)}→${emo(z)}</span>`),
    ...c.relationship.map(relChip), ...c.state.map(stateChip),
  ].join("");
  const tags = [`<span class="tag">${stageName}</span>`];
  if (c.audience_only) tags.push(`<span class="tag ao" title="觀眾看到了，台上的人不知道">只有觀眾知道</span>`);
  if (b.reason.startsWith("set-up")) tags.push(`<span class="tag">鋪陳：還沒有改變</span>`);
  if (b.derived) tags.push(`<span class="tag">反應鏡頭</span>`);
  if (b.story === "B") tags.push(`<span class="tag" title="同一時期另一條在動的故事">副線</span>`);
  if (b.story === "texture") tags.push(`<span class="tag" title="一個平常的時刻，讓高潮有東西可以對比">平常時刻</span>`);
  if (c.expectation) tags.push(`<span class="tag ao" title="${esc(c.expectation)}">觀眾領先</span>`);
  if (b.events.some((e) => e.mind)) tags.push(`<span class="llm" title="這場戲裡有行動是角色的心智（LLM）決定的">LLM</span>`);
  return `<article class="scene${b.derived ? " derived" : ""}${S.scene === b.index ? " on" : ""}" id="sc${b.index}" data-b="${b.index}">
    <div class="row1"><span class="no">${n}</span><span class="intent" title="${esc(tip)}">${esc(name)}</span>${tags.join("")}</div>
    <div class="tbar" title="張力 ${pct(b.tension)}%"><i style="width:${pct(b.tension)}%"></i></div>
    <div class="cap">${esc(caps)}</div>
    <div class="where">${ev.clock ? esc(ev.clock) + " ・ " : ""}${esc(ev.place || "")}${c.obstructs ? `　對手：${esc(c.obstructs)}` : ""}</div>
    <div class="who">${b.who.map(avatar).join("")}</div>
    ${changes ? `<div class="changes">${changes}</div>` : `<div class="wants">這場沒有留下改變</div>`}
    ${c.leaves_question ? `<div class="wants">留下的問題：${esc(c.leaves_question)}</div>` : ""}
    ${speechHtml(b)}
    ${sceneMinds(b)}
    ${seekBtn(ev, b.who_ids && b.who_ids[0], "在現場看這一幕")}
  </article>`;
}

function speechHtml(b) {
  const said = b.events.filter((e) => e.speech && e.speech.say);
  if (!said.length) return "";
  return `<div class="said">${said.slice(0, 3).map((e) => {
    const s = e.speech;
    return `<div class="line"><span class="sp">${esc(s.speaker || "")}</span>「${esc(s.say)}」${s.subtext ? `<span class="sub">（${esc(s.subtext)}）</span>` : ""}
      ${s.answer ? `<div class="line ans"><span class="sp">${esc(s.listener || "")}</span>「${esc(s.answer)}」</div>` : ""}
      ${(s.reactions || []).map((r) => `<div class="line ans"><span class="sp">${esc(r.who)}</span>「${esc(r.say)}」</div>`).join("")}</div>`;
  }).join("")}</div>`;
}

function showStep(i) {
  const ep = dayOf(S.day).episode; const g = ep.grammar[i]; const box = $("#stepdetail"); if (!box) return;
  document.querySelectorAll(".step").forEach((b) => b.setAttribute("aria-expanded", String(+b.dataset.s === S.step)));
  if (S.step == null) { box.innerHTML = ""; return; }
  const name = STEP[g.step][0];
  if (g.step === "new_state" && g.present) {
    const d = g.derived || {}; const bits = [];
    if (d.standing) bits.push("別人對他的看法變了：" + d.standing.map((x) => relChip(x)).join(" "));
    if (d.state) bits.push("世界變了：" + d.state.map(stateChip).join(" "));
    if (d.want) bits.push("他有了新的想要：" + esc(d.want));
    if (d.opening) bits.push(`下一個機會：${STORY[d.opening.kind] || d.opening.kind}${d.opening.against && d.opening.against.length ? "，對 " + esc(d.opening.against.join("、")) : ""}`);
    box.innerHTML = `<b>${name}</b>：` + bits.join("；"); return;
  }
  box.innerHTML = g.present && g.events.length
    ? `<b>${name}</b>：` + g.events.map((e) => `第 ${e.day + 1} 天 ${esc(e.caption)}`).join("；")
    : g.present ? `<b>${name}</b>：${g.note ? esc(g.note) : "有"}` : `<b>${name}</b>：${STEP[g.step][1]}。這個世界沒有產生它，所以這一集不會替它編。`;
}

/* ---------- side: producer ---------- */
function actText(e) {
  const p = e.params || {};
  switch (e.type) {
    case "announce_gathering": return `公告第 ${p.day} 天在${e.place_name || "某處"}舉行${p.kind === "tournament" ? "比武大會" : "門派考核"}`;
    case "deliver_parcel": return `把「${e.object_name || p.object}」送到${e.target_name}手上`;
    case "open_seat": return `「${e.target_name}」的位子空了出來，第 ${p.day} 天決定人選`;
    case "cast_role": return `指派${e.target_name}演「${ROLE[p.role] || p.role}」，對${e.toward_name}，到第 ${p.until} 天`;
    case "announce_visitor": return `傳出消息：${e.target_name}將在第 ${p.day} 天來到${e.place_name}`;
    default: return e.type;
  }
}
const actNote = (e) => ({
  cast_role: "只會讓他更傾向這樣選，不會替他選；規則仍然裁決，他也可能輸",
  announce_gathering: "只是公告：去不去、打不打、誰贏，都是人和規則的事",
  deliver_parcel: "東西送到了，要不要用，是他的事",
  open_seat: "位子空了，誰要爭、誰當選，由派系投票決定",
}[e.type] || "");

function renderProducer() {
  const d = dayOf(S.day); const m = D.meta; const dec = d.producer.decisions[0];
  const phase = d.pacing.phase; const x = Math.min(1, d.pacing.intensity / 4);
  let html = "";
  if (m.strategy === "off") {
    html += `<div class="card sec"><h3>製作人</h3><div class="empty">這個世界沒有製作人，一切都是世界自己發生的。</div></div>`;
  } else {
    const acting = dec && dec.action === "intervene";
    html += `<div class="card sec"><h3>第 ${d.day + 1} 天，製作人…</h3>
      <div class="verdict ${acting ? "act" : ""}"><span class="ic">${acting ? "🎬" : "🤫"}</span><div><div class="big">${acting ? "出手了" : "刻意不動"}</div><div class="dim" style="font-size:12.5px">${acting ? "補上一個故事缺的條件" : "不動也是一種決定"}</div></div></div>
      ${dec ? `<div class="reason">${esc(REASON[dec.reason] || dec.reason)}</div>` : ""}
      ${dec && dec.kind ? `<dl class="kv"><dt>在看的故事</dt><dd>${STORY[dec.kind] || dec.kind}${dec.protagonist ? `：${esc(nameOf(dec.protagonist))}` : ""}</dd>
        ${dec.lacks && dec.lacks.length ? `<dt>它缺</dt><dd>${dec.lacks.map((l) => LACK[l] || l).join("、")}</dd>` : ""}
        ${dec.p_success != null ? `<dt>主角勝算</dt><dd>約 ${pct(dec.p_success)}%（接近五成，才有懸念）</dd>` : ""}</dl>` : ""}
    </div>`;
    const entries = d.producer.entries;
    html += `<div class="card sec"><h3>它做了什麼</h3>${entries.length ? entries.map((e) => `<div class="act-item"><span class="ic">${ICON[e.type] || "•"}</span><div>
      <div class="tt ${e.admitted ? "" : "refused"}">${esc(actText(e))}<span class="str ${STRENGTH[e.type]}">${STRENGTH_ZH[STRENGTH[e.type]]}</span></div>
      <div class="sm">${e.admitted ? `花 ${e.cost} 點。${actNote(e)}` : `<span class="refused">被擋下：${esc(e.reason)}</span>`}</div>
      ${e.purpose ? `<div class="sm" title="只留在製作人自己的帳本，世界從來聽不到">私下的理由：${esc(e.purpose)}</div>` : ""}</div></div>`).join("") : `<div class="empty">這天沒有出手</div>`}</div>`;
    const spent = d.producer.spent_week; const cap = m.week_budget;
    html += `<div class="card sec"><h3>這一週的預算</h3><div class="gauge" aria-label="已用 ${spent} 共 ${cap}">${Array.from({ length: cap }, (_, i) => `<i class="${i < spent ? (spent >= cap ? "warn" : "on") : ""}"></i>`).join("")}</div>
      <div class="scale"><span>已用 ${spent} 點</span><span>每週 ${cap} 點</span></div></div>`;
  }
  html += `<div class="card sec"><h3>世界現在的節奏</h3><div class="meter"><b style="left:${x * 100}%"></b></div>
    <div class="scale"><span>平靜</span><span>升溫中</span><span>高峰</span></div>
    <div class="reason">${PHASE[phase]}：前幾天的轉折越多、越近，數字越高。${phase === "peak" ? "高峰之後，製作人會讓大家喘口氣。" : ""}</div></div>`;
  const acts = D.days.filter(acted).length, stills = D.days.filter(kept).length;
  if (m.strategy !== "off") html += `<div class="card sec"><h3>這一季</h3><dl class="kv"><dt>出手</dt><dd>${acts} 天</dd><dt>刻意不動</dt><dd>${stills} 天</dd></dl></div>`;
  return html;
}
const nameOf = (id) => (D.people.find((p) => p.id === id) || {}).name || id;

/* ---------- side: the stories the world has formed ---------- */
const STATUS = { seeded: "剛冒出來", forming: "成形中", active: "進行中", escalating: "升溫", climax: "高潮", resolved: "已解決", dormant: "休眠" };
const MECH = { face_slap: "打臉", chosen: "被選中", succession: "奪位" };
function renderState() {
  const st = dayOf(S.day).state; if (!st) return `<div class="card sec"><div class="empty">這個世界沒有故事狀態</div></div>`;
  const live = st.arcs.filter((a) => ["seeded", "forming", "active", "escalating", "climax"].includes(a.status));
  const pairs = Object.entries(st.patterns.pairs).filter(([, n]) => n > 1);
  return `<div class="card sec"><h3>在跑的故事線</h3><p class="dim" style="font-size:12.5px;margin-bottom:6px">故事線存在，不代表它在動。「動」是指真的有人心情變了、關係變了一段距離、位子或目標換了。</p>
    ${live.length ? live.map((a) => `<div class="act-item"><span class="ic">${a.stalled ? "⏸" : "▶"}</span><div>
      <div class="tt">${esc(a.question)}</div>
      <div class="sm">${esc(a.people.join("、"))} ・ ${STATUS[a.status] || a.status} ・ ${a.stalled ? `<b class="neg">已經 ${a.stagnation} 天沒有進展</b>` : a.moved_recently ? `最近 7 天有 ${a.moved_recently} 場有進展` : "最近沒有進展"}</div></div></div>`).join("") : '<div class="empty">沒有在跑的故事線</div>'}</div>
  <div class="card sec"><h3>觀眾比眾人先知道</h3>${st.expectations.length ? st.expectations.map((x) => `<div class="act-item"><span class="ic">👁</span><div>
      <div class="tt">${esc(x.name)}</div><div class="sm">真實武功 ${pct(x.knows)}，眾人以為 ${pct(x.expected)}（差 ${pct(x.gap)}）・ 已經等了 ${x.waited} 天</div></div></div>`).join("") : '<div class="empty">沒有人被低估到值得等</div>'}</div>
  <div class="card sec"><h3>快要發生的故事</h3>${st.opportunities.length ? st.opportunities.map((o) => `<div class="act-item"><span class="ic">✨</span><div>
      <div class="tt">${STORY[o.kind] || o.kind}：${esc(o.name)}${o.others.length ? ` 對 ${esc(o.others.join("、"))}` : ""}</div>
      <div class="sm">價值 ${pct(o.potential)} ・ 主角勝算約 ${pct(o.p_success)}%${o.missing.length ? ` ・ 還缺：${o.missing.map((l) => LACK[l] || l).join("、")}` : " ・ 條件都有了"}</div></div></div>`).join("") : '<div class="empty">目前沒有</div>'}</div>
  <div class="card sec"><h3>已經說過的</h3>${Object.keys(st.patterns.mechanics).length ? `<div class="changes">${Object.entries(st.patterns.mechanics).map(([k, n]) => `<span class="cg">${MECH[k] || k} × ${n}</span>`).join("")}</div>` : '<div class="dim">還沒有爽點</div>'}
    ${pairs.length ? `<p class="dim" style="font-size:12.5px;margin-top:6px">同一對人說了不只一次：${pairs.map(([k, n]) => `${esc(k.replace("|", " 和 "))}（${n} 次）`).join("、")}。說得越多，下一次越不新。</p>` : ""}</div>
  <div class="card sec"><h3>積累最多、還沒有出口的人</h3>${st.debts.map((d) => `<div class="act-item"><span class="ic">${esc(String(d.name).slice(-1))}</span><div><div class="tt">${esc(d.name)}（${d.debt.toFixed(1)}）</div>
      <div class="sm">${Object.entries(d.parts).filter(([, v]) => v > 0).map(([k, v]) => `${DEBT[k] || k} ${v.toFixed(1)}`).join(" ・ ") || "沒有"}</div></div></div>`).join("")}</div>`;
}

/* ---------- side: payoffs ---------- */
function renderPayoffs() {
  const list = allPayoffs().sort((a, b) => b.day - a.day || b.event_id - a.event_id); const t = D.totals || {};
  if (!list.length) return `<div class="card sec"><div class="empty">這一季還沒有爽點</div></div>`;
  return `<div class="card sec"><h3>爽點</h3><dl class="kv"><dt>一共</dt><dd>${t.count} 個，其中 ${t.earned_payoffs} 個是自己掙來的</dd><dt>自己掙來</dt><dd>${pct(t.earned_share ?? 0)}%（其餘是製作人的鋪排或運氣）</dd></dl></div>` +
    list.map((p) => `<button class="card pitem" data-d="${p.day}"><div class="t"><span>★ ${PAYOFF[p.kind] || p.kind}：${esc(p.protagonist_name)}${p.against_name ? ` 對 ${esc(p.against_name)}` : ""}</span><span class="dim">第 ${p.day + 1} 天</span></div>
      <div class="s">自己的努力占 ${pct(p.agency)}%；這一刻的份量 ${pct(p.base)}</div>
      <div class="split" title="綠色：他自己掙來的；黃色：製作人的鋪排或運氣"><i class="earn" style="width:${pct(p.base * p.agency)}%"></i><i class="prod" style="width:${pct(p.base * (1 - p.agency))}%"></i></div></button>`).join("");
}

/* ---------- side: people ---------- */
function renderPeople() {
  if (S.person) return personDetail(D.people.find((p) => p.id === S.person));
  const ps = [...D.people].sort((a, b) => b.debt - a.debt);
  return `<div class="card sec"><h3>人物</h3><p class="dim" style="font-size:12.5px">按「積累了多少還沒有出口的東西」排序。被低估的人，真實武功比眾人以為的高。</p></div>` +
    ps.map((p) => {
      const under = p.ability - p.crowd >= 0.12;
      return `<button class="card pcard" data-p="${p.id}"><div class="t">${avatar(p.name)}<span>${esc(p.name)}</span>${under ? '<span class="tag ao">被低估</span>' : ""}<span class="dim" style="margin-left:auto;font-weight:400">${emo(p.emotion)}</span></div>
      <div class="bars"><div class="bl"><span>真實武功</span><span class="track"><i style="width:${pct(p.ability)}%"></i></span><span>${pct(p.ability)}</span></div>
      <div class="bl"><span>眾人以為</span><span class="track"><i class="${under ? "under" : ""}" style="width:${pct(p.crowd)}%"></i></span><span>${pct(p.crowd)}</span></div></div>
      <div class="mini">爽點 ${p.payoffs.length} 個 ・ 積累 ${p.debt.toFixed(1)}${minds().length ? ` ・ 心聲 ${minds().filter((x) => x.person === p.id).length} 則` : ""}</div></button>`;
    }).join("");
}
/* 心聲: what this person thought and did not say, latest first (only a world with minds has any) */
function innerCard(p) {
  const all = minds().filter((x) => x.person === p.id).slice().reverse(); if (!all.length) return "";
  const item = (m) => `<button class="mj" data-mj="${m.n}" title="跳到那一刻（第 ${m.day + 1} 天 ${esc(m.clock)}）"><span class="when">第 ${m.day + 1} 天 ${esc(m.clock)}</span>
    <span class="minner${m.inner ? "" : " none"}">${m.inner ? esc(m.inner) : "（沒有說不出口的想法）"}</span><span class="dim sm">${m.event == null ? "他選了什麼都不做" : `選了：${esc(m.chose)}`}</span></button>`;
  return `<div class="card sec"><h3><span class="llm">LLM</span> 心聲（${all.length} 則）</h3><p class="dim" style="font-size:12.5px;margin-bottom:6px">他心裡想、沒有說出口的。最新的在上面；點一則，跳到那一刻。</p>
    ${all.slice(0, 6).map(item).join("")}${all.length > 6 ? `<details class="more"><summary>更早的 ${all.length - 6} 則</summary>${all.slice(6).map(item).join("")}</details>` : ""}</div>`;
}
function personDetail(p) {
  const parts = Object.entries(p.debt_parts).filter(([, v]) => v > 0);
  return `<button class="back" data-p="">← 回到所有人物</button>
  <div class="card sec"><h3>${avatar(p.name)} ${esc(p.name)}<span class="dim" style="font-weight:400">${p.age ? p.age + " 歲 ・ " : ""}${emo(p.emotion)}</span></h3>
    <div class="row2" style="margin-bottom:8px">${tlOn() && D.timeline.people[p.id] ? `<button class="tlbtn" data-tl="${esc(p.id)}" title="他在整段世界裡每一天的時間軸">看他的時間軸</button>` : ""}${D.world3d ? `<button class="seek" data-seek-t="${S.day * 86400 + 8 * 3600}" data-seek-who="${p.id}">在現場看他（第 ${S.day + 1} 天早上）</button>` : ""}</div>
    <div class="bars"><div class="bl"><span>真實武功</span><span class="track"><i style="width:${pct(p.ability)}%"></i></span><span>${pct(p.ability)}</span></div>
    <div class="bl"><span>眾人以為</span><span class="track"><i class="${p.ability - p.crowd >= 0.12 ? "under" : ""}" style="width:${pct(p.crowd)}%"></i></span><span>${pct(p.crowd)}</span></div>
    <div class="bl"><span>魅力</span><span class="track"><i style="width:${pct(p.charm)}%"></i></span><span>${pct(p.charm)}</span></div></div></div>
  ${innerCard(p)}
  <div class="card sec"><h3>積累了什麼（${p.debt.toFixed(1)}）</h3>${parts.length ? `<div class="changes">${parts.map(([k, v]) => `<span class="cg">${DEBT[k] || k} ${v.toFixed(1)}</span>`).join("")}</div>` : `<div class="dim">沒有</div>`}</div>
  <div class="card sec"><h3>最有關係的人</h3>${p.ties.map((t) => `<div style="margin:5px 0"><b>${esc(t.other_name)}</b> ${t.bond === "dating" ? '<span class="tag ao">交往中</span>' : ""}
    <div class="changes">${["trust", "affection", "respect", "resentment", "attraction"].filter((k) => Math.abs(t[k]) >= 0.05).map((k) => `<span class="cg ${t[k] * REL[k][1] >= 0 ? "up" : "down"}">${REL[k][0]} ${sgn(t[k])}</span>`).join("")}</div></div>`).join("") || '<div class="dim">還沒有</div>'}</div>
  <div class="card sec"><h3>爽點</h3>${p.payoffs.length ? p.payoffs.map((x) => `<div class="act-item"><span class="ic">★</span><div><div class="tt">${PAYOFF[x.kind] || x.kind}${x.against_name ? ` 對 ${esc(x.against_name)}` : ""}</div><div class="sm">自己的努力占 ${pct(x.agency)}%</div></div></div>`).join("") : '<div class="dim">還沒有</div>'}</div>`;
}

/* ---------- the world in 3D (the same world, in a frame) ---------- */
function seekBtn(ev, who, label) {
  if (!D.world3d || !ev || ev.t == null) return "";
  return `<button class="seek" data-seek-t="${ev.t}" data-seek-place="${esc(ev.place_id || "")}" data-seek-who="${esc(who || "")}">▶ ${label}</button>`;
}
function setView(v) {
  S.view = v; document.body.dataset.view = v;
  document.querySelectorAll("#views button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.v === v)));
  $("#worldView").hidden = v !== "world";
  $("#timelineView").hidden = v !== "timeline";
  if (v === "timeline") { renderTimeline(); window.scrollTo({ top: 0 }); }
  if (v === "world") {
    const f = $("#worldFrame");
    if (!f.getAttribute("src")) { S.frameReady = false; f.src = "world/index.html?embed=1"; }
    watchFrame();
    flush();
  } else window.scrollTo({ top: 0 });
}
/* a blank frame is never silent: say why (a file: page cannot load the 3D modules), and offer a reload when it does not answer */
let frameTimer = null;
function watchFrame() {
  const note = $("#worldNote"); clearTimeout(frameTimer);
  if (location.protocol === "file:") {
    note.hidden = false;
    note.innerHTML = "這一頁是用檔案直接打開的，瀏覽器不讓它載入 3D。請改用伺服器打開：<code>python -m channel.studio --preset jianghu</code>，再開 http://127.0.0.1:8795/ 。";
    return;
  }
  if (S.frameReady) { note.hidden = true; return; }
  frameTimer = setTimeout(() => {
    if (S.frameReady || S.view !== "world") return;
    note.hidden = false;
    note.innerHTML = `3D 現場超過 10 秒沒有回應（可能是瀏覽器沒開啟 WebGL，或伺服器已經關了）。<button class="seek" id="frameReload">重新載入 3D</button>`;
    $("#frameReload").onclick = () => { note.hidden = true; S.frameReady = false; $("#worldFrame").src = "world/index.html?embed=1&r=" + Date.now(); watchFrame(); };
  }, 10000);
}
function flush() {
  const f = $("#worldFrame");
  if (S.pending && S.frameReady && f.contentWindow) {
    const p = S.pending; S.pending = null;
    f.contentWindow.postMessage(p.play ? { type: "play", events: p.play } : { type: "seek", ...p }, location.origin);
  }
}
function playEpisode() {
  const ep = dayOf(S.day).episode, w = D.world3d;
  if (!ep || !w) { toast("這個世界沒有 3D 空間"); return; }
  const scenes = ep.beats.filter((b) => b.shoot && !b.derived && b.story !== "texture").flatMap((b) => b.events.slice(0, 1))
    .filter((e) => e.t != null).sort((a, b) => a.t - b.t)
    .map((e) => ({ t: e.t, place: e.place_id, caption: `${e.clock} ${e.caption}` }));
  const ok = scenes.filter((e) => { const d = Math.floor(e.t / 86400); return d >= w.first_day && d <= w.last_day; });
  if (!ok.length) { toast(`這一集的場景不在 3D 回放的範圍內（第 ${w.first_day + 1}–${w.last_day + 1} 天）`); return; }
  S.pending = { play: ok }; setView("world"); flush();
}
function seek(t, place, who) {
  const w = D.world3d;
  if (!w) { toast("這個世界沒有 3D 空間（用空間配方 jianghu_story_spatial_v1 啟動）"); return; }
  const day = Math.floor(t / 86400);
  if (day < w.first_day || day > w.last_day) { toast(`第 ${day + 1} 天不在 3D 回放的範圍內（第 ${w.first_day + 1}–${w.last_day + 1} 天）`); return; }
  S.pending = { t, place, who }; setView("world"); flush();
}
window.addEventListener("message", (e) => {
  if (e.origin !== location.origin || !e.data) return;
  if (e.data.type === "ready") { S.frameReady = true; $("#worldNote").hidden = true; flush(); }
  if (e.data.type === "story") { const day = Math.floor(e.data.t / 86400); setView("story"); select(Math.min(day, D.days.length - 1), true); }
});

/* ---------- the character timeline: one person across the whole world ---------- */
const TLK = {   // kind -> [name, glyph]
  payoff: ["爽點", "★"], love: ["愛情", "♥"], growth: ["突破", "▲"], outburst: ["失控", "⚡"], betrayal: ["背叛與揭穿", "✕"],
  duel: ["比武", "⚔"], switch: ["改投", "⇄"], goal: ["目標改變", "◎"], turn: ["關係轉折", "↻"],
};
const TLN = {   // what the note on a moment says
  love: { accepted: "告白成功", declined: "告白被婉拒", date: "約會", break_up: "分手" },
  outburst: { shove: "推了人", strike: "動手打人", smash: "砸東西", break_down: "崩潰" },
  betrayal: { lie_exposed: "謊言被揭穿", distortion_exposed: "扭曲被揭穿", concealment_exposed: "隱瞞被揭穿", caught: "人贓俱獲", false: "冤枉了人", steal: "偷竊" },
  switch: { found: "成立派系", join: "加入", leave: "離開派系", change: "改投別人" },
  goal: { formed: "立下目標", transformed: "目標轉變", abandoned: "放棄目標", completed: "完成目標" },
  payoff: PAYOFF,
};
const tlOn = () => !!(D.timeline && D.timeline.people);
let tlCache = null;
function tlIndex() {
  if (!tlCache || tlCache.src !== D.timeline) tlCache = { src: D.timeline, by: Object.fromEntries(D.timeline.events.map((e) => [`${e.id}:${e.k}`, e])) };
  return tlCache.by;
}
function tlItems(pid) {   // every moment and every turn of one person, in time order; unknown fields and kinds are tolerated
  const p = D.timeline.people[pid]; const by = tlIndex();
  const ev = (p.ev || []).map((k) => by[k] && { ...by[k], key: k }).filter(Boolean);
  const turns = (p.turns || []).map((t) => ({ ...t, k: "turn", id: t.e, key: `t${t.e}:${t.o}:${t.f}` }));
  return [...ev, ...turns].sort((a, b) => a.t - b.t || String(a.k).localeCompare(b.k));
}
function tlRole(it, pid) {   // what the person was in that moment, in words
  if (it.k === "payoff") return it.h === pid ? "他是主角" : "他是對手";
  if (it.k === "duel") return it.h === pid ? "他贏了" : "他輸了";
  if (it.k === "love" || it.k === "outburst" || it.k === "betrayal") return it.h ? (it.h === pid ? "他主動" : "他是對方") : "";
  return "";
}
function tlText(it) {
  if (it.k === "turn") return `${nameOf(it.o)}對他的${(REL[it.f] || [it.f])[0]}翻${it.y > 0 ? "正了" : "負了"}（現在 ${sgn(it.z)}）`;
  const note = (TLN[it.k] || {})[it.n]; const cap = it.cap || "";
  return cap + (note && !cap.includes(note) ? `（${note}${it.x ? "：" + it.x : ""}）` : it.x ? `（${it.x}）` : "");
}
const tlPlace = (it) => (D.timeline.places || {})[it.plid] || "";
function tlSeekBtn(it, pid) {
  const w = D.world3d; if (!w) return "";
  const out = it.d < w.first_day || it.d > w.last_day;
  return `<button class="seek${out ? " off" : ""}" data-seek-t="${it.t}" data-seek-place="${esc(it.plid || "")}" data-seek-who="${esc(pid)}" title="${out ? `這一天不在 3D 回放的範圍內（第 ${w.first_day + 1}–${w.last_day + 1} 天）` : "在 3D 世界裡，停在這一刻、這個地方，跟著他"}">▶ 在現場看${out ? "（超出範圍）" : ""}</button>`;
}
function tlDefault() {
  const ids = D.people.map((p) => p.id).filter((id) => D.timeline.people[id]);
  return ids.slice().sort((a, b) => tlItems(b).length - tlItems(a).length || (a < b ? -1 : 1))[0] || null;
}
function tlJump(day, beat, explain) {
  setView("story"); select(Math.max(0, Math.min(D.days.length - 1, day)), false);
  if (beat != null && $(`#sc${beat}`)) focusScene(beat);
  else { window.scrollTo({ top: 0 }); if (explain) toast(`第 ${day + 1} 天：這件事沒有被拍進那一集的場景，已帶你到那一天的集`); }
}
function renderTimeline() {
  const box = $("#tlBody"), bar = $("#tlPeople");
  if (!tlOn()) {
    bar.innerHTML = ""; box.innerHTML = `<div class="card sec"><div class="empty">這個世界是舊版程式留下來的，沒有時間軸的資料。重新用 python -m channel.studio 產生一次，就會有。</div></div>`; return;
  }
  const T = D.timeline;
  const ids = D.people.map((p) => p.id).filter((id) => T.people[id]);
  if (!S.tlPerson || !T.people[S.tlPerson]) S.tlPerson = tlDefault();
  const pid = S.tlPerson, tp = T.people[pid] || {}, n = (tp.mood || []).length;
  bar.innerHTML = ids.map((id) => `<button class="tlp" role="tab" data-tp="${esc(id)}" aria-selected="${id === pid}">${avatar(nameOf(id))}<span>${esc(nameOf(id))}</span><span class="cnt" title="重要時刻加關係轉折">${tlItems(id).length}</span></button>`).join("");
  if (!pid || !n) { box.innerHTML = `<div class="card sec"><div class="empty">還沒有資料</div></div>`; return; }
  const items = tlItems(pid), kinds = Object.keys(TLK);
  const role = tp.role || "";
  const leads = [...role].map((c, i) => (c === "L" ? i : -1)).filter((i) => i >= 0), supports = [...role].filter((c) => c === "S").length;
  const count = Object.fromEntries(kinds.map((k) => [k, items.filter((x) => x.k === k).length]));
  const shown = items.filter((x) => !S.tlHide.has(x.k));
  const person = D.people.find((p) => p.id === pid) || {};
  const last = (tp.emo || [])[n - 1];

  const avail = Math.max(260, box.clientWidth - 40), LW = avail < 560 ? 60 : 92;
  const CW = Math.max(46, Math.min(84, Math.floor((avail - LW) / n)));
  const row = (label, cells, cls = "") => `<div class="tlrow ${cls}"><div class="tlrl">${label}</div>${cells}</div>`;
  const dayCells = Array.from({ length: n }, (_, d) => {
    const dd = dayOf(d), ep = dd && dd.episode;
    return `<button class="tlday" data-jump="1" data-d="${d}" title="第 ${d + 1} 天${ep ? "：" + esc(ep.core_question) : "：沒有集"}"><span class="n">${d + 1}</span><i class="${dd ? kindOf(dd) : "none"}"></i></button>`;
  }).join("");
  const roleCells = Array.from({ length: n }, (_, d) => {
    const c = role[d] || ".", ep = (dayOf(d) || {}).episode;
    const word = c === "L" ? "主角" : c === "S" ? "配角" : "";
    return word ? `<button class="tlcell role r${c}" data-jump="1" data-d="${d}" title="第 ${d + 1} 天：他是這一集的${word}${ep ? "。" + esc(ep.core_question) : ""}">${word}</button>`
      : `<span class="tlcell role r0" title="第 ${d + 1} 天：這一集沒有他">·</span>`;
  }).join("");
  // mood: a line through the days; above the middle line the day was pleasant, below it was not
  const H = 104, MID = H / 2, W = n * CW, X = (d) => d * CW + CW / 2, Y = (v) => MID - Math.max(-1, Math.min(1, v)) * (MID - 12);
  const mood = tp.mood, pts = mood.map((v, d) => [X(d), Y(v)]);
  const path = pts.map(([x, y], d) => `${d ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const bands = [...role].map((c, d) => (c === "L" || c === "S" ? `<rect class="band ${c}" x="${d * CW}" y="0" width="${CW}" height="${H}"/>` : "")).join("");
  const dots = pts.map(([x, y], d) => `<circle class="md ${mood[d] >= 0 ? "pos" : "neg"}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5" data-jump="1" data-d="${d}" tabindex="0" role="button" aria-label="第 ${d + 1} 天 ${emo((tp.emo || [])[d])}"><title>第 ${d + 1} 天：${emo((tp.emo || [])[d])}（心情 ${sgn(mood[d])}）</title></circle>`).join("");
  const moodSvg = `<svg class="tlsvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="group" aria-label="${esc(nameOf(pid))}每天的心情">${bands}<line class="zero" x1="0" x2="${W}" y1="${MID}" y2="${MID}"/><path class="mline" d="${path}"/>${dots}</svg>`;
  const marker = (it) => {
    const [kn, g] = TLK[it.k] || [it.k, "•"]; const cls = it.k === "turn" ? ` ${it.y > 0 ? "up" : "down"} wide` : "";
    const lab = it.k === "turn" ? `${it.y > 0 ? "↑" : "↓"}${esc(String(nameOf(it.o)).slice(-2))}` : g;
    return `<button class="tlev k-${esc(it.k)}${cls}" data-jump="1" data-d="${it.d}" data-b="${it.b ?? ""}" data-x="1" title="${esc(kn)}：${esc(tlText(it))}">${lab}</button>`;
  };
  const cellsOf = (test) => Array.from({ length: n }, (_, d) => `<div class="tlcell evs">${shown.filter((x) => x.d === d && test(x)).map(marker).join("")}</div>`).join("");
  const grid = `<div class="tlscroll" tabindex="0" aria-label="時間軸，可以左右捲動"><div class="tlgrid" style="--cw:${CW}px;--lw:${LW}px;--n:${n}">
    ${row("天", dayCells, "hd")}${row("角色", roleCells)}
    <div class="tlrow"><div class="tlrl" title="越高越愉快">心情<br><span class="dim">愉快在上</span></div><div class="tlmood" style="grid-column:2 / span ${n}">${moodSvg}</div></div>
    ${row("重要時刻", cellsOf((x) => x.k !== "turn"))}${row("關係轉折", cellsOf((x) => x.k === "turn"))}</div></div>`;
  const legend = `<div class="tllegend" role="group" aria-label="哪些標記要顯示">${kinds.map((k) => `<button class="tlf k-${k}" data-tk="${k}" aria-pressed="${!S.tlHide.has(k)}"${count[k] ? "" : ' data-empty="1"'}><span class="g">${TLK[k][1]}</span>${TLK[k][0]}<b>${count[k]}</b></button>`).join("")}</div>`;
  const byDay = {}; shown.forEach((it) => { (byDay[it.d] = byDay[it.d] || []).push(it); });
  const list = Object.keys(byDay).map(Number).sort((a, b) => a - b).map((d) => `<div class="tlday-h">第 ${d + 1} 天${role[d] === "L" ? '<span class="tag ao">他是主角</span>' : role[d] === "S" ? '<span class="tag">他是配角</span>' : ""}</div>` +
    byDay[d].map((it) => {
      const [kn, g] = TLK[it.k] || [it.k, "•"]; const rw = tlRole(it, pid);
      const where = [it.c, tlPlace(it)].filter(Boolean).join(" ・ ");
      return `<div class="tlitem" data-jump="1" data-d="${it.d}" data-b="${it.b ?? ""}" data-x="1" tabindex="0" role="button" aria-label="${esc(tlText(it))}">
        <span class="tlev k-${esc(it.k)}${it.k === "turn" ? (it.y > 0 ? " up" : " down") : ""} static">${g}</span>
        <div class="body"><div class="top"><b>${esc(kn)}</b>${rw ? `<span class="tag">${rw}</span>` : ""}<span class="dim sm">${esc(where)}</span></div>
        <div class="cap">${esc(tlText(it))}</div>
        ${it.b == null ? '<div class="dim sm">這件事沒有被拍進那一集的場景，會帶你到那一天</div>' : ""}</div>
        <div class="acts"><span class="go">到這一集</span>${tlSeekBtn(it, pid)}</div></div>`;
    }).join("")).join("");
  box.innerHTML = `
  <div class="card sec tlsum"><div class="who1">${avatar(nameOf(pid))}<div><div class="nm">${esc(nameOf(pid))}</div><div class="dim sm">${person.age ? person.age + " 歲 ・ " : ""}最後一天的心情：${emo(last)}</div></div></div>
    <div class="facts"><span class="fact yes">主角 ${leads.length} 集</span><span class="fact">配角 ${supports} 集</span><span class="fact no">沒出現 ${n - leads.length - supports} 天</span>
      <span class="fact">重要時刻 ${items.filter((x) => x.k !== "turn").length} 件</span><span class="fact">關係轉折 ${count.turn} 次</span></div>
    ${leads.length ? `<div class="leads"><span class="dim sm">他是主角的集：</span>${leads.slice(0, 14).map((d) => `<button class="cg" data-jump="1" data-d="${d}" title="${esc(((dayOf(d) || {}).episode || {}).core_question || "")}">第 ${d + 1} 天</button>`).join("")}${leads.length > 14 ? `<span class="dim sm">…還有 ${leads.length - 14} 集</span>` : ""}</div>` : ""}
    <div class="row2"><button data-tlperson="${esc(pid)}">到他的人物頁</button>${D.world3d ? `<button class="seek" data-seek-t="${(n - 1) * 86400 + 8 * 3600}" data-seek-who="${esc(pid)}">在現場看他（第 ${n} 天早上）</button>` : ""}</div></div>
  <div class="card block"><h3>每一天</h3><p class="note">${n} 天，最早的在左邊。底色深的是他當主角的那天，淺的是配角。每個標記都能點，會跳到那一集；圖例可以點，把不想看的種類收起來。</p>${legend}${grid}</div>
  <div class="card block"><h3>發生了什麼</h3><p class="note">${shown.length ? `照時間順序，${shown.length} 件。點一列，到那一集的那一幕；「在現場看」到 3D 的同一刻。` : "沒有符合的標記（圖例都被收起來了，或這個人還沒有重要的事）。"}</p><div class="tllist">${list}</div></div>`;
}

/* ---------- switching worlds ---------- */
async function worldPicker() {
  let cat;
  try { const r = await fetch("../../worlds.json", { cache: "no-store" }); if (!r.ok) return; cat = await r.json(); } catch (_) { return; }   // opened from a file: one world only
  const here = location.pathname.split("/")[1];
  const sel = $("#worldSel");
  sel.innerHTML = cat.worlds.map((w) => `<option value="${esc(w.key)}"${w.key === here ? " selected" : ""}>${esc(w.title)} ・ 種子 ${w.seed} ・ ${w.days} 天${w.live ? "" : "（只能看）"}</option>`).join("") + `<option value="__new">＋ 新增一個世界…</option>`;
  $("#worldPick").hidden = false;
  $("#nwPreset").innerHTML = Object.entries(cat.presets).map(([k, t]) => `<option value="${esc(k)}">${esc(t)}</option>`).join("");
  sel.addEventListener("change", () => {
    if (sel.value !== "__new") { location.href = `../../${sel.value}/site/index.html`; return; }
    sel.value = here; $("#newWorld").showModal();
  });
  $("#nwCancel").addEventListener("click", () => $("#newWorld").close());
  $("#nwForm").addEventListener("submit", async (e) => {
    e.preventDefault(); const go = $("#nwGo"); go.disabled = true; go.textContent = "建造中…（請等 1～3 分鐘）";
    try {
      const q = new URLSearchParams({ preset: $("#nwPreset").value, days: $("#nwDays").value }); if ($("#nwSeed").value) q.set("seed", $("#nwSeed").value);
      const r = await fetch(`../../new?${q}`, { method: "POST" }); const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      location.href = `../../${j.key}/site/index.html`;
    } catch (err) { go.disabled = false; go.textContent = "建造"; toast("建造失敗：" + err.message); }
  });
}

/* ---------- wiring ---------- */
function renderSide() {
  document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.t === S.tab)));
  $("#pane").innerHTML = S.tab === "producer" ? renderProducer() : S.tab === "state" ? renderState() : S.tab === "payoffs" ? renderPayoffs() : renderPeople();
}
function select(n, scroll = true) {
  S.day = Math.max(0, Math.min(D.days.length - 1, n)); S.scene = null; S.step = null;
  history.replaceState(null, "", `#d=${S.day + 1}`);
  renderStrip(); renderEpisode(); renderSide();
  if (scroll) window.scrollTo({ top: 0, behavior: "smooth" });
}
function focusScene(b) {
  S.scene = b; document.querySelectorAll(".scene").forEach((s) => s.classList.toggle("on", +s.dataset.b === b));
  document.querySelectorAll(".chart .pt").forEach((s) => s.classList.toggle("on", +s.dataset.b === b));
  const el = $(`#sc${b}`); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
}
async function go(n) {
  if (D.meta.mind) { toast("這個世界只能看，不能再走：它的每個決定都是 LLM 當初回答的，已經付費的答案只到第 " + D.days.length + " 天；再走下去要問新的問題，會用掉額度。要多走幾天，請用 soul_lab.py（在有額度的那一天）再跑，然後重開這一頁。"); return; }
  const btns = [$("#go1"), $("#go7")]; btns.forEach((b) => { b.disabled = true; });
  try {
    const r = await fetch(`advance?n=${n}`, { method: "POST" });
    if (r.status === 409) { toast("這個世界是上次留下來的，只能看，不能再走。換一個世界，或新增一個。"); return; }
    if (!r.ok) throw new Error(r.status);
    const fresh = await (await fetch("studio.json", { cache: "no-store" })).json();
    D = fresh; window.STUDIO = fresh; renderHeader(); select(D.days.length - 1, false); if (S.view === "timeline") renderTimeline(); toast(`世界又走了 ${n} 天`);
    const f = $("#worldFrame"); if (f.getAttribute("src")) { S.frameReady = false; f.src = "world/index.html?embed=1&r=" + Date.now(); }
  } catch (e) {
    toast("這個頁面沒有連到程式。用 python -m channel.studio 啟動，才能讓世界再走一天。");
  } finally { btns.forEach((b) => { b.disabled = false; }); }
}

function bind() {
  $("#strip").addEventListener("click", (e) => { const b = e.target.closest(".day"); if (b) select(+b.dataset.d, false); });
  $("#filters").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return; S.filter = b.dataset.f;
    document.querySelectorAll("#filters button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); renderStrip();
  });
  $("#tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.tab = b.dataset.t; S.person = null; renderSide(); });
  $("#pane").addEventListener("click", (e) => {
    const mj = e.target.closest("[data-mj]"); if (mj) { focusMind(+mj.dataset.mj); return; }
    const tl = e.target.closest("[data-tl]"); if (tl) { S.tlPerson = tl.dataset.tl; setView("timeline"); return; }
    const p = e.target.closest("[data-p]"); if (p) { S.person = p.dataset.p || null; renderSide(); return; }
    const d = e.target.closest(".pitem"); if (d) select(+d.dataset.d);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".seek"); if (!b) return;
    if (b.dataset.play) { playEpisode(); return; }
    seek(+b.dataset.seekT, b.dataset.seekPlace || undefined, b.dataset.seekWho || undefined);
  });
  const tlView = $("#timelineView");
  tlView.addEventListener("click", (e) => {
    if (e.target.closest(".seek")) return;   // the global handler goes to the 3D world
    const tp = e.target.closest("[data-tp]"); if (tp) { S.tlPerson = tp.dataset.tp; renderTimeline(); return; }
    const tk = e.target.closest("[data-tk]"); if (tk) { const k = tk.dataset.tk; if (S.tlHide.has(k)) S.tlHide.delete(k); else S.tlHide.add(k); renderTimeline(); return; }
    const pp = e.target.closest("[data-tlperson]"); if (pp) { S.tab = "people"; S.person = pp.dataset.tlperson; setView("story"); renderSide(); return; }
    const j = e.target.closest("[data-jump]"); if (j) tlJump(+j.dataset.d, j.dataset.b === "" || j.dataset.b == null ? null : +j.dataset.b, !!j.dataset.x);
  });
  tlView.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.dataset && e.target.dataset.jump && e.target.tagName !== "BUTTON") { e.preventDefault(); e.target.dispatchEvent(new MouseEvent("click", { bubbles: true })); }
  });
  let rz = null;
  window.addEventListener("resize", () => { if (S.view !== "timeline") return; clearTimeout(rz); rz = setTimeout(renderTimeline, 150); });
  $("#views").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.v === "world" && !D.world3d) { toast("這個世界沒有 3D 空間（用空間配方 jianghu_story_spatial_v1 啟動）"); return; }
    setView(b.dataset.v);
  });
  $("#episode").addEventListener("click", (e) => {
    const sc0 = e.target.closest("[data-scene]"); if (sc0) { focusScene(+sc0.dataset.scene); return; }
    const s = e.target.closest(".step"); if (s) { S.step = S.step === +s.dataset.s ? null : +s.dataset.s; showStep(S.step); return; }
    const pt = e.target.closest(".pt"); if (pt) { focusScene(+pt.dataset.b); return; }
    const sc = e.target.closest(".scene"); if (sc) focusScene(+sc.dataset.b);
  });
  $("#episode").addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target.classList && e.target.classList.contains("pt")) { e.preventDefault(); focusScene(+e.target.dataset.b); } });
  document.addEventListener("keydown", (e) => {
    if (S.view !== "story" || (e.target.closest && e.target.closest("input, textarea, select"))) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); select(S.day - 1, false); }
    if (e.key === "ArrowRight") { e.preventDefault(); select(S.day + 1, false); }
  });
  $("#go1").addEventListener("click", () => go(1)); $("#go7").addEventListener("click", () => go(7));
  $("#helpBtn").addEventListener("click", (e) => { const h = $("#help"); h.hidden = !h.hidden; e.currentTarget.setAttribute("aria-expanded", String(!h.hidden)); });
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = next;
    try { localStorage.setItem("studio-theme", next); } catch (_) { /* a private window: the choice is simply not kept */ }
  });
  try { const t = localStorage.getItem("studio-theme"); if (t) document.documentElement.dataset.theme = t; } catch (_) { /* not available */ }
}

(async () => {
  try { D = await load(); } catch (e) { $("#episode").innerHTML = `<div class="card ephead"><div class="question">讀不到資料</div><p class="dim">用 python -m channel.studio --new 17 --days 14 產生，再開這一頁。</p></div>`; return; }
  const m = /#d=(\d+)/.exec(location.hash); S.day = m ? Math.min(D.days.length - 1, Math.max(0, +m[1] - 1)) : D.days.length - 1;
  bind(); renderHeader(); renderStrip(); renderEpisode(); renderSide(); worldPicker();
})();
})();
