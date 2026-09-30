/* Jev Playground —— 前端逻辑（无框架、无构建步骤）
 *
 * 设计要点：
 *   1. 凡是枚举参数一律用选择控件，不让用户手打：model 和 question type 都是多选框。
 *   2. API Key 永远不进浏览器 —— 由本地 Python 服务端持有并代为请求。
 *   3. 结果按答案类型分别可视化（noul 概率条 / choice 概率分布 / score 档位梯）。
 */
(() => {
  "use strict";

  /* ------------------------------------------------------------------ 工具 */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  const pct = (v) => (v == null ? "—" : (v * 100).toFixed(1) + "%");
  const num = (v, d = 3) => (v == null ? "—" : Number(v).toFixed(d).replace(/\.?0+$/, "") || "0");

  /* ------------------------------------------------------------------ 常量 */
  const TYPES = {
    choice: { label: "choice", desc: "从固定选项里选一个" },
    score: { label: "score", desc: "沿有序档位打分（2~10 档）" },
    noul: { label: "noul", desc: "是／否判断，返回 0~1 的概率" },
  };
  const STATE_MODES = [
    { key: "string", label: "字符串" },
    { key: "object", label: "JSON 对象" },
    { key: "array", label: "JSON 数组" },
  ];
  const LS_KEY = "jev.playground.history.v1";
  const LS_THEME = "jev.playground.theme";

  /* ------------------------------------------------------------------ 状态 */
  const S = {
    cfg: null,
    picked: new Set(),
    stateMode: "string",
    questions: [],
    uid: 0,
    busy: false,
    lastRequest: null,
    history: [],
  };

  /* ------------------------------------------------------------------ 启动 */
  init();

  async function init() {
    applyTheme(localStorage.getItem(LS_THEME) || "dark");
    S.history = loadHistory();

    renderStateModes();
    renderTypes();
    bindEvents();

    try {
      const res = await fetch("/api/config");
      S.cfg = await res.json();
    } catch (err) {
      setConn(false, "无法连接本地服务");
      say("本地服务异常：" + err.message, "danger");
      return;
    }

    renderModels();
    renderPresets();
    renderHistory();

    if (S.cfg.configured) {
      setConn(true, "Key 已就绪 · " + S.cfg.key_source);
    } else {
      setConn(false, "未配置 Key");
      banner(
        "还没有找到可用的 <code>TYPESAFE_API_KEY</code>。请在项目根目录的 <code>.env</code> 第 8 行填入密钥后" +
          "<b>刷新本页</b>；或直接点右上角主题按钮旁的状态查看详情。领取地址：console.typesafe.ai/keys"
      );
    }

    // 默认选中服务端配置的模型
    const fallback = S.cfg.model_alias || "jev-latest";
    if (S.cfg.models.includes(fallback)) S.picked.add(fallback);
    else if (S.cfg.models.length) S.picked.add(S.cfg.models[0]);
    renderModels();
    updateEstimate();
  }

  /* ------------------------------------------------------------------ 主题 */
  function applyTheme(mode) {
    document.documentElement.dataset.theme = mode;
    try {
      localStorage.setItem(LS_THEME, mode);
    } catch (e) {
      /* 忽略无痕模式下的写入失败 */
    }
  }

  /* ------------------------------------------------------------------ 提示 */
  function setConn(ok, text) {
    const el = $("#conn");
    el.className = "pill " + (ok ? "ok" : "bad");
    el.textContent = (ok ? "● " : "● ") + text;
  }
  function banner(html) {
    const el = $("#banner");
    el.innerHTML = "<span>⚠️</span><div>" + html + "</div>";
    el.classList.remove("hidden");
  }
  function say(msg, kind) {
    const out = $("#out");
    out.innerHTML =
      '<div class="rerr"><span class="kind">' +
      esc(kind || "错误") +
      "</span><br>" +
      esc(msg) +
      "</div>";
  }

  /* ================================================================ 渲染 · 模型 */
  function renderModels() {
    const models = (S.cfg && S.cfg.models) || [];
    const box = $("#models");
    if (!models.length) {
      box.innerHTML = '<span class="hint">未能获取模型列表</span>';
      return;
    }
    box.innerHTML = models
      .map(
        (m) => `
      <label class="chk" title="${esc(describeModel(m))}">
        <input type="checkbox" value="${esc(m)}" ${S.picked.has(m) ? "checked" : ""}>
        <span>${esc(m)}</span>
        ${m.indexOf("latest") > -1 || m.indexOf("preview") > -1 ? '<span class="tag">alias</span>' : '<span class="tag">pinned</span>'}
      </label>`
      )
      .join("");

    $$("#models input").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) S.picked.add(input.value);
        else S.picked.delete(input.value);
        updateEstimate();
      });
    });
  }
  function describeModel(m) {
    const map = (S.cfg && S.cfg.model_notes) || {};
    return map[m] || m;
  }

  /* ================================================================ 渲染 · 预设 */
  function renderPresets() {
    const sel = $("#preset");
    const presets = (S.cfg && S.cfg.presets) || [];
    sel.innerHTML =
      '<option value="">载入预设场景…</option>' +
      presets.map((p) => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join("");
    sel.addEventListener("change", () => {
      const p = presets.find((x) => x.id === sel.value);
      if (p) loadPreset(p);
    });
  }

  function loadPreset(p) {
    S.stateMode = p.state_mode || "string";
    $("#stateText").value =
      p.state_mode === "string" ? p.state : JSON.stringify(p.state, null, 2);
    renderStateModes();

    S.questions = [];
    S.uid = 0;
    Object.keys(p.questions || {}).forEach((id) => {
      const q = p.questions[id];
      S.questions.push({
        uid: ++S.uid,
        id: id,
        type: q.type,
        instructions:
          typeof q.instructions === "string" ? q.instructions : JSON.stringify(q.instructions, null, 2),
        criteria: fromApiCriteria(q.type, q.criteria),
      });
    });
    if (p.model && (S.cfg.models || []).includes(p.model)) {
      S.picked = new Set([p.model]);
    }
    renderModels();
    renderTypes();
    renderQuestions();
    updateEstimate();
    if (p.note) noteUnder("#stateText", p.note);
  }

  function noteUnder(sel, text) {
    let el = $(sel + " + .note");
    if (!el) {
      el = document.createElement("div");
      el.className = "note";
      $(sel).insertAdjacentElement("afterend", el);
    }
    el.textContent = text;
  }

  /* ================================================================ 渲染 · state 形态 */
  function renderStateModes() {
    const box = $("#stateModes");
    box.innerHTML = STATE_MODES.map(
      (m) =>
        `<button type="button" data-mode="${m.key}" aria-pressed="${S.stateMode === m.key}">${m.label}</button>`
    ).join("");
    $$("#stateModes button").forEach((b) =>
      b.addEventListener("click", () => {
        S.stateMode = b.dataset.mode;
        renderStateModes();
        updateEstimate();
      })
    );
  }

  /* ================================================================ 渲染 · 问题类型多选 */
  function renderTypes() {
    const box = $("#types");
    const active = new Set(S.questions.map((q) => q.type));
    box.innerHTML = Object.keys(TYPES)
      .map(
        (t) => `
      <label class="chk" title="${esc(TYPES[t].desc)}">
        <input type="checkbox" value="${t}" ${active.has(t) ? "checked" : ""}>
        <span>${esc(TYPES[t].label)}</span>
      </label>`
      )
      .join("");

    $$("#types input").forEach((input) => {
      input.addEventListener("change", () => {
        const type = input.value;
        if (input.checked) {
          S.questions.push(newQuestion(type));
        } else {
          S.questions = S.questions.filter((q) => q.type !== type);
        }
        renderTypes();
        renderQuestions();
        updateEstimate();
      });
    });
  }

  function newQuestion(type) {
    const base = { uid: ++S.uid, id: "", type: type, instructions: "" };
    const used = new Set(S.questions.map((q) => q.id));
    let n = S.questions.filter((q) => q.type === type).length + 1;
    let id = type + "_" + n;
    while (used.has(id)) id = type + "_" + ++n;
    base.id = id;

    if (type === "choice") base.criteria = [{ k: "", v: "" }];
    else if (type === "score") base.criteria = ["", ""];
    else base.criteria = { enabled: false, t: "", f: "" };
    return base;
  }

  /* ================================================================ 渲染 · 问题卡片 */
  function renderQuestions() {
    const box = $("#questions");
    if (!S.questions.length) {
      box.innerHTML = '<div class="hint">还没有问题。勾选上面的类型，或载入一个预设场景。</div>';
      $("#qCount").textContent = "";
      return;
    }
    box.innerHTML = S.questions.map(renderCard).join("");
    bindCards();
    $("#qCount").textContent =
      "共 " + S.questions.length + " 个问题 · 它们会在同一次请求里并行评估同一份 state";
  }

  function renderCard(q) {
    let criteriaHtml = "";
    if (q.type === "choice") {
      criteriaHtml = `
        <div class="sub">criteria · 选项名 → 说明（键会出现在返回的 choice 与 probabilities 里）</div>
        ${q.criteria
          .map(
            (row, i) => `
          <div class="critrow" data-i="${i}">
            <span class="ord">${i}</span>
            <input class="input sm mono k" placeholder="选项名" value="${esc(row.k)}" data-f="k">
            <input class="input sm v" placeholder="说明（会发给模型，写成能互相区分的样子）" value="${esc(row.v)}" data-f="v">
            <button type="button" class="ghost icon delrow" title="删除该选项">✕</button>
          </div>`
          )
          .join("")}
        <div class="row" style="margin:6px 0 0">
          <button type="button" class="ghost sm addrow">＋ 加选项</button>
          <span class="hint">最多 255 项；建议留一个「其他／以上都不是」兜底</span>
        </div>`;
    } else if (q.type === "score") {
      criteriaHtml = `
        <div class="sub">criteria · 有序档位，从低到高（数组顺序即编号 0…n，2~10 档）</div>
        ${q.criteria
          .map(
            (lv, i) => `
          <div class="critrow" data-i="${i}">
            <span class="ord">${i}</span>
            <input class="input sm v" placeholder="第 ${i} 档的说明" value="${esc(lv)}" data-f="level">
            <button type="button" class="ghost icon delrow" title="删除该档">✕</button>
          </div>`
          )
          .join("")}
        <div class="row" style="margin:6px 0 0">
          <button type="button" class="ghost sm addrow">＋ 加档位</button>
          <span class="hint">官方：score 的档位在数值标定上很弱，只用来判断是否越过阈值</span>
        </div>`;
    } else {
      const c = q.criteria || { enabled: false, t: "", f: "" };
      criteriaHtml = `
        <label class="chk" style="width:fit-content">
          <input type="checkbox" class="noulcrit" ${c.enabled ? "checked" : ""}>
          <span>补充 criteria（可选）</span>
        </label>
        ${
          c.enabled
            ? `<input class="input sm t" placeholder="true 的说明：什么算「是」" value="${esc(c.t)}">
               <input class="input sm f" placeholder="false 的说明：什么算「否」" value="${esc(c.f)}">`
            : '<div class="hint">不填也能用。判断标准有歧义时再补，会显著提升稳定性。</div>'
        }`;
    }

    return `
    <div class="qcard" data-uid="${q.uid}">
      <div class="qhead">
        <span class="qtype ${q.type}">${esc(q.type)}</span>
        <input class="input sm mono qidinput qid" value="${esc(q.id)}" title="问题 ID：只给你的代码用，不会发送给模型">
        <span class="hint grow">ID 不参与推理</span>
        <button type="button" class="ghost icon dup" title="复制一个问题（同类型）">⧉</button>
        <button type="button" class="ghost icon rm" title="删除">✕</button>
      </div>
      <div class="qbody">
        <textarea class="input sm mono instr" rows="2" spellcheck="false"
          placeholder="instructions：你要问的确切问题。以 { 或 [ 开头会被识别为结构化 instructions。">${esc(q.instructions)}</textarea>
        <div class="err qerr"></div>
        ${criteriaHtml}
      </div>
    </div>`;
  }

  function bindCards() {
    $$("#questions .qcard").forEach((card) => {      const uid = Number(card.dataset.uid);
      const q = S.questions.find((x) => x.uid === uid);
      if (!q) return;

      $(".qid", card).addEventListener("input", (e) => (q.id = e.target.value.trim()));
      $(".instr", card).addEventListener("input", (e) => (q.instructions = e.target.value));

      $(".rm", card).addEventListener("click", () => {
        S.questions = S.questions.filter((x) => x.uid !== uid);
        renderTypes();
        renderQuestions();
        updateEstimate();
      });
      $(".dup", card).addEventListener("click", () => {
        const copy = JSON.parse(JSON.stringify(q));
        copy.uid = ++S.uid;
        copy.id = q.id + "_copy";
        S.questions.push(copy);
        renderQuestions();
      });

      // choice / score 的行编辑
      $$(".critrow", card).forEach((row) => {
        const i = Number(row.dataset.i);
        // 注意：choice 的一行里有「选项名」和「说明」两个输入框，必须逐个绑定，
        // 只取第一个会让「说明」框变成哑的。
        $$("[data-f]", row).forEach((field) => {
          field.addEventListener("input", () => {
            const kind = field.dataset.f;
            if (q.type === "choice") {
              if (kind === "k") q.criteria[i].k = field.value;
              else q.criteria[i].v = field.value;
            } else if (kind === "level") {
              q.criteria[i] = field.value;
            }
          });
        });
        $(".delrow", row).addEventListener("click", () => {
          if (q.type === "choice" && q.criteria.length <= 1) return;
          if (q.type === "score" && q.criteria.length <= 2) return;
          q.criteria.splice(i, 1);
          renderQuestions();
        });
      });

      const addRow = $(".addrow", card);
      if (addRow) {
        addRow.addEventListener("click", () => {
          if (q.type === "choice") {
            if (q.criteria.length >= 255) return;
            q.criteria.push({ k: "", v: "" });
          } else {
            if (q.criteria.length >= 10) return;
            q.criteria.push("");
          }
          renderQuestions();
          focusLastRow(uid);
        });
      }

      const nc = $(".noulcrit", card);
      if (nc) {
        nc.addEventListener("change", () => {
          q.criteria = q.criteria || { enabled: false, t: "", f: "" };
          q.criteria.enabled = nc.checked;
          renderQuestions();
        });
        const t = $(".t", card);
        const f = $(".f", card);
        if (t) t.addEventListener("input", () => (q.criteria.t = t.value));
        if (f) f.addEventListener("input", () => (q.criteria.f = f.value));
      }
    });
  }

  /* 新增一行后把焦点送到新行的第一个输入框 */
  function focusLastRow(uid) {
    const card = $('#questions .qcard[data-uid="' + uid + '"]');
    if (!card) return;
    const rows = $$(".critrow", card);
    const last = rows[rows.length - 1];
    if (!last) return;
    const input = $("[data-f]", last);
    if (input) input.focus();
  }

  /* ================================================================ 校验与构造 */
  function parseMaybeJson(text) {
    const s = text.trim();
    if (!s || (s[0] !== "{" && s[0] !== "[")) return null;
    try {
      return JSON.parse(s);
    } catch (e) {
      return null;
    }
  }

  function buildState() {
    const text = $("#stateText").value;
    if (S.stateMode === "string") {
      if (!text.trim()) return { error: "state 不能为空" };
      return { value: text };
    }
    if (!text.trim()) return { error: "state 不能为空" };
    try {
      const parsed = JSON.parse(text);
      if (S.stateMode === "object" && (typeof parsed !== "object" || Array.isArray(parsed)))
        return { error: "当前形态是「JSON 对象」，但内容不是对象" };
      if (S.stateMode === "array" && !Array.isArray(parsed))
        return { error: "当前形态是「JSON 数组」，但内容不是数组" };
      return { value: parsed };
    } catch (e) {
      return { error: "JSON 解析失败：" + e.message };
    }
  }

  function buildQuestions() {
    const map = {};
    const problems = [];
    const seen = new Set();

    S.questions.forEach((q, idx) => {
      const label = q.id || "第 " + (idx + 1) + " 个问题";
      if (!q.id) problems.push(label + "：ID 不能为空");
      else if (seen.has(q.id)) problems.push(label + "：ID 重复");
      seen.add(q.id);

      const instr = q.instructions.trim();
      if (!instr) problems.push(label + "：instructions 不能为空");

      const obj = { type: q.type };
      const parsedInstr = parseMaybeJson(instr);
      obj.instructions = parsedInstr === null ? instr : parsedInstr;

      if (q.type === "choice") {
        const crit = {};
        q.criteria.forEach((row) => {
          if (row.k.trim()) crit[row.k.trim()] = row.v.trim() || row.k.trim();
        });
        const n = Object.keys(crit).length;
        if (n < 1) problems.push(label + "：choice 至少需要 1 个有效选项名");
        if (n > 255) problems.push(label + "：choice 最多 255 个选项");
        obj.criteria = crit;
      } else if (q.type === "score") {
        const levels = q.criteria.map((s) => String(s).trim()).filter(Boolean);
        if (levels.length < 2) problems.push(label + "：score 至少需要 2 个档位");
        if (levels.length > 10) problems.push(label + "：score 最多 10 个档位");
        obj.criteria = levels;
      } else {
        const c = q.criteria || {};
        if (c.enabled && (c.t.trim() || c.f.trim())) {
          obj.criteria = { true: c.t.trim(), false: c.f.trim() };
        }
      }

      if (q.id) map[q.id] = obj;
    });

    return { map: map, problems: problems };
  }

  /* ================================================================ 调用 */
  async function submit() {
    if (S.busy) return;
    if (!S.cfg || !S.cfg.configured) {
      say("尚未配置 API Key。请在 .env 里填入 TYPESAFE_API_KEY 后刷新页面。", "未配置");
      return;
    }

    const picked = Array.from(S.picked);
    $("#modelsErr").textContent = picked.length ? "" : "请至少选择一个模型";
    if (!picked.length) return;

    const st = buildState();
    $("#stateErr").textContent = st.error || "";
    if (st.error) return;

    const bq = buildQuestions();
    if (bq.problems.length) {
      say(bq.problems.join("\n"), "请求不合法");
      $$("#questions .qerr").forEach((e) => (e.textContent = ""));
      return;
    }

    const payload = { state: st.value, questions: bq.map };
    S.lastRequest = { payload: payload, models: picked };

    S.busy = true;
    const btn = $("#submit");
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span> 调用中…';
    $("#out").innerHTML = '<div class="empty"><div class="spin" style="width:22px;height:22px"></div><div>正在调用 ' +
      picked.length + " 个模型…</div></div>";

    const results = await Promise.all(
      picked.map(async (m) => {
        try {
          const res = await fetch("/api/eval", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model: m, state: payload.state, questions: payload.questions }),
          });
          const data = await res.json();
          return Object.assign({ alias: m }, data);
        } catch (err) {
          return { alias: m, ok: false, kind: "网络错误", error: err.message };
        }
      })
    );

    S.busy = false;
    btn.disabled = false;
    btn.innerHTML = '调用 Jev <kbd>⌘↵</kbd>';

    renderResults(results, bq.map);
    pushHistory(payload, picked, results);
  }

  /* ================================================================ 渲染 · 结果 */
  function renderResults(results, questions) {
    const ids = Object.keys(questions);
    let html = "";

    if (results.length > 1) html += renderComparison(results, ids);

    results.forEach((r) => {
      html += '<div class="rcard">';
      if (!r.ok) {
        html +=
          '<div class="rhead"><span class="rmodel">' +
          esc(r.alias) +
          '</span><span class="pill bad">' +
          esc(r.kind || "失败") +
          "</span></div>";
        html +=
          '<div class="rerr" style="margin-top:9px"><span class="kind">' +
          esc(r.kind || "调用失败") +
          "</span><br>" +
          esc(r.error || "未知错误") +
          (r.hint ? '<div class="note" style="margin-top:8px">' + esc(r.hint) + "</div>" : "") +
          "</div>";
        html += "</div>";
        return;
      }

      const u = r.usage || {};
      html +=
        '<div class="rhead"><span class="rmodel">' +
        esc(r.model || r.alias) +
        "</span>" +
        (r.model && r.model !== r.alias ? '<span class="pill">别名 ' + esc(r.alias) + "</span>" : "") +
        "</div>";
      html +=
        '<div class="rmeta">' +
        "<span>" + num(r.latency_ms, 0) + " ms</span>" +
        "<span>in " + (u.input_tokens ?? "—") + " tok</span>" +
        "<span>out " + (u.output_tokens ?? "—") + " tok</span>" +
        "<span>≈ $" + (r.cost_usd != null ? Number(r.cost_usd).toFixed(8) : "—") + "</span>" +
        (r.attempts > 1 ? "<span>重试 " + (r.attempts - 1) + " 次</span>" : "") +
        "</div>";

      ids.forEach((id) => {
        html += renderAnswer(id, questions[id], (r.answers || {})[id]);
      });

      html +=
        "<details><summary>原始响应 JSON</summary><pre>" +
        esc(JSON.stringify({ model: r.model, answers: r.answers, usage: r.usage }, null, 2)) +
        "</pre></details>";
      html += "</div>";
    });

    $("#out").innerHTML = html;
  }

  function renderComparison(results, ids) {
    const okResults = results.filter((r) => r.ok);
    if (okResults.length < 2) return "";
    let html = '<div class="rcard"><div class="rhead"><span class="rmodel">多模型对比</span>' +
      '<span class="hint">同一个请求发给多个模型，逐题对照</span></div>';
    html += '<table class="cmp"><thead><tr><th>问题</th>';
    okResults.forEach((r) => (html += "<th>" + esc(r.model || r.alias) + "</th>"));
    html += "</tr></thead><tbody>";

    ids.forEach((id) => {
      const vals = okResults.map((r) => summarize((r.answers || {})[id]));
      const allSame = vals.every((v) => v === vals[0]);
      html += "<tr><td>" + esc(id) + "</td>";
      vals.forEach((v) => (html += '<td class="' + (allSame ? "same" : "diff") + '">' + esc(v) + "</td>"));
      html += "</tr>";
    });
    html += "</tbody></table>";
    html += '<div class="note" style="margin-top:9px">标黄的单元格表示各模型答案不一致 —— ' +
      "这通常意味着这一题的判断不稳定，或者该题的 instructions 需要写得更明确。</div></div>";
    return html;
  }

  function summarize(a) {
    if (!a) return "—";
    if (a.type === "noul") return num(a.noul, 3);
    if (a.type === "choice") return a.choice + " (" + num(a.confidence, 2) + ")";
    if (a.type === "score") return num(a.score, 2) + " (" + num(a.confidence, 2) + ")";
    return JSON.stringify(a);
  }

  function confClass(c) {
    if (c == null) return "";
    const act = (S.cfg && S.cfg.confidence_act) || 0.9;
    const mid = (S.cfg && S.cfg.confidence_confirm) || 0.6;
    if (c >= act) return "high";
    if (c >= mid) return "mid";
    return "low";
  }

  function renderAnswer(id, q, a) {
    let head =
      '<div class="ahead"><span class="aid">' +
      esc(id) +
      '</span><span class="qtype ' +
      esc((q && q.type) || "") +
      '">' +
      esc((q && q.type) || "?") +
      "</span>";

    if (!a) {
      return (
        head +
        '<span class="conf low">无返回</span></div><div class="hint">响应里没有这个问题的答案</div></div>'
      );
    }

    // ---------- noul
    if (a.type === "noul") {
      const v = a.noul;
      const yes = v >= 0.5;
      return (
        head +
        "</div>" +
        '<div class="noulval ' +
        (yes ? "yes" : "no") +
        '">' +
        '<div class="noulnum">' +
        num(v, 3) +
        "</div>" +
        "<div style=\"flex:1\">" +
        '<div class="verdict">判为 <b>' +
        (yes ? "是" : "否") +
        "</b>（阈值 0.5）· " +
        (yes ? "置信度即该概率本身" : "不确定") +
        "</div>" +
        '<div class="bar track" style="margin-top:7px"><i style="width:' +
        (v * 100).toFixed(1) +
        '%"></i></div>' +
        "</div></div>" +
        '<div class="note">noul 没有 confidence 字段；0.5 表示是与否等概率，不是「中等程度」。</div>'
      );
    }

    // ---------- choice
    if (a.type === "choice") {
      const probs = a.probabilities || {};
      const rows = Object.keys(probs)
        .map((k) => ({ k: k, p: probs[k] }))
        .sort((x, y) => y.p - x.p);
      return (
        head +
        '<span class="conf ' +
        confClass(a.confidence) +
        '">confidence ' +
        num(a.confidence, 3) +
        "</span></div>" +
        rows
          .map(
            (r) =>
              '<div class="prow ' +
              (r.k === a.choice ? "win" : "") +
              '"><span class="pname" title="' +
              esc(r.k) +
              '">' +
              esc(r.k) +
              (r.k === a.choice ? " ✓" : "") +
              '</span><span class="bar"><i style="width:' +
              (Math.max(0, Math.min(1, r.p)) * 100).toFixed(1) +
              '%"></i></span><span class="pval">' +
              num(r.p, 3) +
              "</span></div>"
          )
          .join("")
      );
    }

    // ---------- score
    if (a.type === "score") {
      const legend = a.legend || {};
      const probs = a.probabilities || {};
      let bestIdx = null;
      let best = -1;
      Object.keys(probs).forEach((k) => {
        if (probs[k] > best) {
          best = probs[k];
          bestIdx = k;
        }
      });
      const keys = Object.keys(legend).sort((x, y) => Number(x) - Number(y));
      return (
        head +
        '<span class="conf ' +
        confClass(a.confidence) +
        '">confidence ' +
        num(a.confidence, 3) +
        "</span></div>" +
        '<div class="row" style="margin:0 0 8px"><span class="scoreval">' +
        num(a.score, 3) +
        '</span><span class="hint">概率加权的期望位置，可能落在两档之间</span></div>' +
        '<div class="ladder">' +
        keys
          .map(
            (k) =>
              '<div class="lrow ' +
              (k === bestIdx ? "hit" : "") +
              '"><span class="lnum">' +
              esc(k) +
              '</span><span class="ltext">' +
              esc(legend[k]) +
              '</span><span class="lp">' +
              num(probs[k], 3) +
              "</span></div>"
          )
          .join("") +
        "</div>" +
        '<div class="note">高亮的是概率最高的一档。不要用 score 在两档之间插值反推精确数值。</div>'
      );
    }

    return head + "</div><pre>" + esc(JSON.stringify(a, null, 2)) + "</pre>";
  }

  /* ================================================================ 历史 */
  function loadHistory() {
    try {
      return JSON.parse(localStorage.getItem(LS_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }
  function pushHistory(payload, models, results) {
    const ok = results.filter((r) => r.ok);
    S.history.unshift({
      t: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      models: models,
      state: payload.state,
      stateMode: S.stateMode,
      questions: payload.questions,
      ms: ok.length ? Math.round(ok[0].latency_ms) : null,
    });
    S.history = S.history.slice(0, 15);
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(S.history));
    } catch (e) {
      /* 配额满就放弃持久化 */
    }
    renderHistory();
  }
  function renderHistory() {
    const box = $("#hist");
    const list = $("#histList");
    if (!S.history.length) {
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");
    list.innerHTML = S.history
      .map((h, i) => {
        const qn = Object.keys(h.questions || {}).length;
        const preview =
          typeof h.state === "string" ? h.state : JSON.stringify(h.state);
        return (
          '<div class="hrow" data-i="' +
          i +
          '"><span class="ht">' +
          esc(h.t) +
          '</span><span class="hs">' +
          esc(preview.slice(0, 90)) +
          '</span><span class="ht">' +
          qn +
          "问 · " +
          esc((h.models || []).join(",")) +
          "</span></div>"
        );
      })
      .join("");
    $$("#histList .hrow").forEach((row) =>
      row.addEventListener("click", () => restore(Number(row.dataset.i)))
    );
  }
  function restore(i) {
    const h = S.history[i];
    if (!h) return;
    S.stateMode = h.stateMode || "string";
    $("#stateText").value =
      typeof h.state === "string" ? h.state : JSON.stringify(h.state, null, 2);
    S.questions = [];
    S.uid = 0;
    Object.keys(h.questions || {}).forEach((id) => {
      const q = h.questions[id];
      S.questions.push({
        uid: ++S.uid,
        id: id,
        type: q.type,
        instructions:
          typeof q.instructions === "string" ? q.instructions : JSON.stringify(q.instructions, null, 2),
        criteria: fromApiCriteria(q.type, q.criteria),
      });
    });
    S.picked = new Set(h.models || []);
    renderStateModes();
    renderModels();
    renderTypes();
    renderQuestions();
    updateEstimate();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ================================================================ 成本预估 */
  function updateEstimate() {
    const text = $("#stateText").value || "";
    const qText = JSON.stringify(S.questions.map((q) => [q.instructions, q.criteria]));
    const tokens = Math.round((text.length + qText.length) / 3.4);
    const n = Math.max(1, S.picked.size);
    const cost = (tokens * n * 0.042) / 1e6;
    $("#estCost").textContent =
      "预估输入 ≈ " + tokens.toLocaleString() + " tok × " + n + " 模型 ≈ $" + cost.toFixed(6);
  }

  /* ================================================================ 预设互转 */
  function fromApiCriteria(type, criteria) {
    if (type === "choice") {
      const rows = Object.keys(criteria || {}).map((k) => ({ k: k, v: String(criteria[k] ?? "") }));
      return rows.length ? rows : [{ k: "", v: "" }];
    }
    if (type === "score") {
      const arr = (criteria || []).map((x) => String(x));
      return arr.length >= 2 ? arr : ["", ""];
    }
    const c = criteria || {};
    const enabled = Boolean(c.true || c.false);
    return { enabled: enabled, t: c.true || "", f: c.false || "" };
  }

  /* ================================================================ 事件 */
  function bindEvents() {
    $("#form").addEventListener("submit", (e) => {
      e.preventDefault();
      submit();
    });
    $("#stateText").addEventListener("input", updateEstimate);

    $("#clearBtn").addEventListener("click", () => {
      $("#stateText").value = "";
      $("#stateErr").textContent = "";
      S.questions = [];
      S.uid = 0;
      renderTypes();
      renderQuestions();
      renderStateModes();
      updateEstimate();
      $("#out").innerHTML =
        '<div class="empty"><div class="big">{ }</div><div>已清空，重新构造一个请求吧</div></div>';
    });

    $("#themeBtn").addEventListener("click", () => {
      applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });

    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    });
  }
})();
