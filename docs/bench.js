/* Misty Step Bench — renders manifest + bench_packet.v1 files. No build, no deps. */
(async function () {
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const pct = (x) => (x * 100).toFixed(1) + '%';
  const humanMs = (ms) => ms >= 60000 ? Math.floor(ms/60000) + 'm ' + Math.round((ms%60000)/1000) + 's' : (ms/1000).toFixed(1) + 's';
  const shortModel = (slug) => String(slug || '').split('/').pop();

  const manifest = await (await fetch('data/manifest.json')).json();

  /* ---------- index ---------- */
  const cardsEl = $('#cards');
  if (cardsEl) {
    // One card per benchmark FAMILY; editions of the same benchmark are
    // lineage inside the card, never sibling cards.
    const families = new Map();
    for (const b of manifest.benchmarks) {
      const key = b.family || b.id;
      if (!families.has(key)) families.set(key, []);
      families.get(key).push(b);
    }
    cardsEl.innerHTML = [...families.values()].map((eds) => {
      const cur = eds[0]; // manifest order: current edition first
      const runs = eds.reduce((n, e) => n + e.packets.length, 0);
      const lineage = eds.map((e, i) =>
        `<a href="benchmark.html?id=${encodeURIComponent(e.id)}">${esc(e.edition)}${i === 0 ? ' (current)' : ''}</a>`).join(' · ');
      return `
      <div class="card">
        <span class="tag">${esc(cur.edition)} · ${cur.tasks} tasks</span>
        <h2><a href="benchmark.html?id=${encodeURIComponent(cur.id)}">${esc(cur.family_title || cur.title)}</a></h2>
        <p>${esc(cur.tagline)}</p>
        <div class="foot"><span>${runs} published run${runs === 1 ? '' : 's'} across ${eds.length} edition${eds.length === 1 ? '' : 's'}</span><span>${esc(cur.grader)}</span></div>
        <div class="editions">editions: ${lineage}</div>
      </div>`;
    }).join('');
    const reviewCards = $('#review-cards');
    if (reviewCards) {
      reviewCards.innerHTML = (manifest.reviews || []).map((review) => `
        <a class="review-card" href="${esc(review.url)}">
          <span class="review-card-status">${esc(review.status)}</span>
          <h2>${esc(review.title)}</h2>
          <p>${esc(review.tagline)}</p>
          <span class="review-card-link">inspect evidence →</span>
        </a>`).join('');
    }
    return;
  }

  /* ---------- benchmark page ---------- */
  const id = new URLSearchParams(location.search).get('id');
  const bench = manifest.benchmarks.find((b) => b.id === id);
  const root = $('#bench');
  if (!bench) { root.innerHTML = '<p class="muted">Unknown benchmark.</p>'; return; }
  document.title = bench.title + ' — Misty Step Bench';

  const packets = await Promise.all(bench.packets.map((p) => fetch('data/' + p).then((r) => r.json())));
  packets.sort((a, b) => b.score.point - a.score.point || a.config.model.localeCompare(b.config.model));

  const drift = (p) => p.response_model && p.response_model !== p.config.model
    ? `<span class="drift" title="provider served a different backing model">served ${esc(p.response_model)}</span>` : '';

  const leaderboard = packets.map((p) => {
    const s = p.score;
    const when = new Date(p.executed_at_unix_ms).toISOString().slice(0, 10);
    const cost = p.totals && p.totals.cost_usd != null ? '$' + p.totals.cost_usd.toFixed(4) : '—';
    const dur = p.totals && p.totals.duration_ms != null ? humanMs(p.totals.duration_ms) : null;
    const lead = p === packets[0] ? ' is-lead' : '';
    return `<div class="lb-row">
      <div class="lb-model"><div class="name">${esc(shortModel(p.config.model))}</div>
        <div class="when num">${when} · ${esc(p.provenance?.repo || '?')}@${esc((p.provenance?.git_sha || '').slice(0, 7))}</div></div>
      <div class="lb-score">
        <div class="ae-ci${lead}">
          <div class="ae-ci-band" style="left:${s.lower * 100}%;width:${(s.upper - s.lower) * 100}%"></div>
          <div class="ae-ci-mean" style="left:${s.point * 100}%"></div>
        </div>
        <div class="lb-nums num"><b>${pct(s.point)}</b><span>${s.successes}/${s.n}</span><span>95% CI [${pct(s.lower)}, ${pct(s.upper)}]</span><span>${cost}</span>${dur ? `<span>${dur} model-time</span>` : ''}${drift(p)}</div>
      </div>
    </div>`;
  }).join('');

  /* task explorer: join tasks across packets by task_id */
  const byTask = new Map();
  for (const p of packets) for (const t of p.tasks) {
    if (!byTask.has(t.task_id)) byTask.set(t.task_id, { def: t, outs: [] });
    byTask.get(t.task_id).outs.push({ model: shortModel(p.config.model), output: t.output, passed: t.passed });
  }

  const grading = (t) => {
    const e = t.expectation || {};
    const plain = {
      exact: () => `output must be exactly <code>${esc(e.value)}</code>`,
      contains: () => `output must contain <code>${esc(e.value)}</code>`,
      icontains: () => `output must contain (case-insensitive) <code>${esc(e.value)}</code>`,
      regex: () => `constraint checked mechanically <details><summary>raw pattern</summary> <code>${esc(e.value ?? e.pattern)}</code></details>`,
    }[e.kind];
    return plain ? plain() : esc(e.kind || 'unknown');
  };

  const tasks = [...byTask.values()].map(({ def, outs }) => `
    <details class="task">
      <summary>
        <span class="t-id">${esc(def.task_id)}</span>
        <span class="t-sum">${esc(def.summary || '')}</span>
        <span class="t-dots">${outs.map((o) => `<span class="dot ${o.passed ? 'ok' : 'fail'}" title="${esc(o.model)}: ${o.passed ? 'pass' : 'fail'}"></span>`).join('')}</span>
      </summary>
      <div class="t-body">
        <div class="t-prompt"><span class="lab">prompt</span>${esc(def.prompt)}</div>
        <div class="t-grading"><span class="lab">grading</span> ${grading(def)}</div>
        <div class="outs">${outs.map((o) => `
          <div class="out">
            <div class="who"><span>${esc(o.model)}</span><span class="verdict ${o.passed ? 'ok' : 'fail'}">${o.passed ? 'PASS' : 'FAIL'}</span></div>
            <pre>${esc(o.output)}</pre>
          </div>`).join('')}</div>
      </div>
    </details>`).join('');

  /* method table from packets */
  const method = `<div class="scroll"><table class="ae-table">
    <tr><th>model</th><th>provider</th><th>temp</th><th>max&nbsp;tokens</th><th>tokens</th><th>cost</th><th>model-time</th><th>config id</th></tr>
    ${packets.map((p) => `<tr class="num">
      <td class="mono">${esc(p.config.model)}</td><td>${esc(p.config.provider)}</td>
      <td>${p.config.temperature ?? '—'}</td><td>${p.config.max_tokens ?? '—'}</td>
      <td>${p.totals?.tokens ?? '—'}</td><td>${p.totals?.cost_usd != null ? '$' + p.totals.cost_usd.toFixed(4) : '—'}</td>
      <td>${p.totals?.duration_ms != null ? humanMs(p.totals.duration_ms) : '—'}</td>
      <td class="mono cfgid">${esc(p.config.config_id)}</td>
    </tr>`).join('')}
  </table></div>
  <p>System prompt (identical across runs):</p>
  <pre>${esc(packets[0]?.config.system_prompt || '')}</pre>
  <p>Reproduce with your own key:</p>
  <pre>OPENROUTER_API_KEY=&lt;your key&gt; crucible run benchmarks/${esc(bench.id)}.json --model &lt;slug&gt;</pre>`;

  /* notes: minimal markdown (h1/h2, ul, p, code, bold) */
  let notesHtml = '';
  try {
    const md = await (await fetch('data/notes/' + bench.id + '.md')).text();
    notesHtml = md.split(/\n{2,}/).map((blk) => {
      if (/^##\s/.test(blk)) return '<h2>' + inline(blk.replace(/^##\s*/, '')) + '</h2>';
      if (/^#\s/.test(blk)) return '<h1>' + inline(blk.replace(/^#\s*/, '')) + '</h1>';
      if (/^\|.*\|\s*$/m.test(blk)) {
        const rows = blk.split('\n').filter((l) => /^\|.*\|\s*$/.test(l.trim()));
        const cells = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        const isRule = (l) => /^[\s|:-]+$/.test(l);
        const head = cells(rows[0]);
        const body = rows.slice(1).filter((l) => !isRule(l));
        return '<div class="scroll"><table><thead><tr>' + head.map((c) => '<th>' + inline(c) + '</th>').join('') +
          '</tr></thead><tbody>' + body.map((r) => '<tr>' + cells(r).map((c) => '<td>' + inline(c) + '</td>').join('') + '</tr>').join('') +
          '</tbody></table></div>';
      }
      if (/^[-*]\s/m.test(blk)) {
        const items = [];
        for (const l of blk.split('\n')) {
          if (/^[-*]\s/.test(l.trim())) items.push(l.replace(/^\s*[-*]\s*/, ''));
          else if (items.length) items[items.length - 1] += ' ' + l.trim();
        }
        return '<ul>' + items.map((it) => '<li>' + inline(it) + '</li>').join('') + '</ul>';
      }
      return '<p>' + inline(blk) + '</p>';
    }).join('\n');
  } catch (e) { notesHtml = '<p class="muted">No notes yet.</p>'; }
  function inline(s) {
    return esc(s.replace(/\n/g, ' '))
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
      .replace(/\*([^*]+)\*/g, '<i>$1</i>');
  }

  const siblings = manifest.benchmarks.filter((b) => (b.family || b.id) === (bench.family || bench.id));
  const lineage = siblings.length > 1
    ? ' · editions: ' + siblings.map((b) => b.id === bench.id
        ? `<a class="cur">${esc(b.edition)}</a>`
        : `<a href="benchmark.html?id=${encodeURIComponent(b.id)}">${esc(b.edition)}</a>`).join(' ')
    : '';
  root.innerHTML = `
    <div class="bhead">
      <h1>${esc(bench.family_title || bench.title)} <span class="muted">· ${esc(bench.edition)}</span></h1>
      <p class="slug">${esc(bench.id)} · <a href="${esc(bench.spec_url)}">spec</a> · ${bench.tasks} tasks · ${esc(bench.grader)}${lineage}</p>
      <p class="thesis">${esc(bench.thesis)}</p>
      <div class="chips">${(bench.families || []).map((f) => `<span class="ae-chip">${esc(f)}</span>`).join('')}</div>
    </div>
    <section><p class="sect-title">Results</p><div class="lb">${leaderboard}</div></section>
    <section><p class="sect-title">Lab notes</p><div class="notes">${notesHtml}</div></section>
    <section><p class="sect-title">Tasks &amp; outputs</p>
      <div class="legendbar"><span>each dot = one model, in leaderboard order</span></div>
      <div class="tasks">${tasks}</div></section>
    <section><p class="sect-title">Method &amp; reproduction</p><div class="method">${method}</div></section>`;
})();
