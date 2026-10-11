const $ = (id) => document.getElementById(id);

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Minimal Markdown: headings, bold, italics, lists, paragraphs. Input is escaped first.
function md(src) {
  const inline = (t) => esc(t)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const line of String(src ?? "").split("\n")) {
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) {
      closeList();
      const level = Math.min(m[1].length + 2, 5);
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
    } else if ((m = line.match(/^\s*[-*]\s+(.*)/)) || (m = line.match(/^\s*\d+\.\s+(.*)/))) {
      const tag = /^\s*\d+\./.test(line) ? "ol" : "ul";
      if (list !== tag) { closeList(); out.push(`<${tag}>`); list = tag; }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  return out.join("\n");
}

const list = (items) => items.length
  ? `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`
  : "<em>None</em>";

// ---------- one renderer per kind of stage output ----------

const renderBrief = (b) => `
  <dl class="fields">
    <dt>Audience</dt><dd>${esc(b.audience)}</dd>
    <dt>Content type</dt><dd>${esc(b.content_type)}</dd>
    <dt>Purpose</dt><dd>${esc(b.purpose)}</dd>
    <dt>Tone</dt><dd>${esc(b.tone)}</dd>
    <dt>Key messages</dt><dd>${list(b.key_messages)}</dd>
    <dt>Assumptions</dt><dd>${list(b.assumptions)}</dd>
  </dl>`;

const renderOutline = (o) => `
  <ol class="outline">${o.sections.map((s) => `
    <li><b>${esc(s.heading)}</b> <span class="words">~${esc(s.approx_words)} words</span>
      <p>${esc(s.point)}</p></li>`).join("")}
  </ol>`;

const renderDraft = (d) => `<h3>${esc(d.title)}</h3><div class="content">${md(d.body_markdown)}</div>`;

const renderReview = (r) => `
  <div class="score-line">
    <span class="score">${esc(r.score)}<small>/10</small></span>
    <span>${esc(r.summary)}</span>
  </div>
  ${r.issues.length ? `<ul class="issues">${r.issues.map((i) => `
    <li class="issue ${esc(i.severity)}">
      <div class="issue-head"><span class="badge ${esc(i.severity)}">${esc(i.severity)}</span>
        <span class="badge id">${esc(i.id)}</span></div>
      <p>${esc(i.problem)}</p>
      <p class="fix"><b>Fix:</b> ${esc(i.fix)}</p>
    </li>`).join("")}</ul>` : "<p><em>No issues found.</em></p>"}
  ${r.missing_key_messages?.length ? `<h4>Missing key messages</h4>${list(r.missing_key_messages)}` : ""}`;

const renderFinal = (f) => `
  <h3>${esc(f.title)}</h3><div class="content">${md(f.final_markdown)}</div>
  <h4>How each review issue was handled</h4>
  ${f.resolved.length ? `<ul class="resolved">${f.resolved.map((x) => `
    <li><span class="badge id">${esc(x.issue_id)}</span><span>${esc(x.how)}</span></li>`).join("")}</ul>`
    : "<p><em>None</em></p>"}`;

const STAGES = {
  understand: { n: "1", title: "Brief", render: renderBrief },
  outline: { n: "2", title: "Outline", render: renderOutline },
  draft: { n: "3", title: "Draft", render: renderDraft },
  review: { n: "4", title: "Review", render: renderReview },
  improve: { n: "5", title: "Improved draft", render: renderDraft },
  final: { n: "6", title: "Final content", render: renderFinal },
  "re-review": { n: "+", title: "Re-review of final content", render: renderReview },
};

// ---------- step cards ----------

let current = null;  // card of the stage that is running

function addCard(stage, model) {
  const [base, round] = stage.split("#");
  const info = STAGES[base] || { n: "?", title: base, render: (d) => `<pre>${esc(JSON.stringify(d, null, 2))}</pre>` };
  const li = document.createElement("li");
  li.className = "step running";
  li.innerHTML = `
    <span class="marker" aria-hidden="true"></span>
    <article class="card">
      <header class="card-head">
        <h2>${info.n}. ${esc(info.title)}${round ? ` · round ${esc(round)}` : ""}</h2>
        <span class="model">${esc(model)}</span>
        <span class="state">Running…</span>
      </header>
      <div class="card-body"><ul class="log"></ul></div>
    </article>`;
  $("steps").appendChild(li);
  li.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return { li, info };
}

function log(text, cls = "") {
  if (!current) return;
  const item = document.createElement("li");
  item.className = cls;
  item.textContent = text;
  current.li.querySelector(".log").appendChild(item);
}

function setState(text) {
  if (current) current.li.querySelector(".state").textContent = text;
}

function finishCard(event) {
  const { li, info } = current;
  li.className = "step done";
  setState(`Done · ${event.seconds}s`);
  li.querySelector(".card-body").innerHTML = info.render(event.data) +
    `<details><summary>Raw JSON passed to the next step</summary><pre>${esc(JSON.stringify(event.data, null, 2))}</pre></details>`;
  current = null;
}

function summary(html, cls) {
  const el = $("summary");
  el.hidden = !html;
  el.className = `summary ${cls || ""}`;
  el.innerHTML = html || "";
}

// ---------- event stream ----------

const HANDLERS = {
  stage_start: (e) => { current = addCard(e.stage, e.model); },
  status: (e) => { setState(`${e.text}…`); log(e.text); },
  wait: (e) => {
    setState(`Rate limited · waiting ${Math.round(e.seconds)}s`);
    log(`Rate limited on ${e.model} (free tier) — waiting ${Math.round(e.seconds)}s, then retrying`, "wait");
  },
  stage_done: finishCard,
  blocked: (e) => {
    if (current) {
      current.li.className = "step blocked";
      setState("Blocked");
      log(e.detail, "bad");
    }
    summary(`<b>Blocked:</b> harmful content detected (${esc(e.where)}). Nothing after this point was generated or shown.`, "blocked");
  },
  error: (e) => {
    if (current) { current.li.className = "step blocked"; setState("Failed"); log(e.detail, "bad"); }
    summary(`<b>Error:</b> ${esc(e.detail)}`, "error");
  },
  done: (e) => {
    const r = e.result;
    const up = r.score_after > r.score_before;
    const rounds = r.rounds > 1 ? ` in ${r.rounds} improve rounds (${r.score_history.join(" → ")})` : "";
    summary(`Review score <b>${r.score_before}</b> → <b>${r.score_after}</b>/10${rounds}. ` +
      (up ? "Improved." : "Did not improve."), up ? "ok" : "");
  },
};

async function run(idea) {
  const res = await fetch("/api/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idea }),
  });
  if (!res.ok || !res.body) throw new Error(`Server returned ${res.status}`);

  // Server-sent events: blocks of "data: {json}" separated by a blank line.
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let cut;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      if (!chunk.startsWith("data: ")) continue;
      const event = JSON.parse(chunk.slice(6));
      HANDLERS[event.type]?.(event);
    }
  }
}

$("examples").addEventListener("change", (e) => {
  if (e.target.value) $("idea").value = e.target.value;
});

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const idea = $("idea").value.trim();
  if (!idea) return;
  $("run").disabled = true;
  $("steps").innerHTML = "";
  current = null;
  summary("Running… each step appears below as soon as it finishes.");
  try {
    await run(idea);
  } catch (err) {
    summary(`<b>Error:</b> ${esc(err.message)}`, "error");
  } finally {
    $("run").disabled = false;
  }
});
