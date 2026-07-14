/* Seam Agency v0 — renders a checked-in qualification receipt. No run controls. */
(async function () {
  const root = document.querySelector('#qualification-review');
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const pct = (value) => (value * 100).toFixed(1) + '%';
  const shortSha = (sha) => String(sha).slice(0, 12);
  const monoValue = (value) => value == null ? '<span class="null-value">null</span>' : esc(value);
  const sourceUrl = (path) => `https://github.com/misty-step/bench/blob/master/${path}`;

  let review;
  try {
    const response = await fetch('data/reviews/seam-agency-v0-qualification.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    review = await response.json();
  } catch (error) {
    root.innerHTML = `<p class="review-error">Could not load the checked-in qualification receipt: ${esc(error.message)}</p>`;
    return;
  }

  const run = review.run;
  const score = run.score;
  const usage = run.model_usage;
  const executed = new Date(run.created_at_unix_ms).toISOString();

  const tasks = review.tasks.map((task) => {
    const capability = task.capability_receipt;
    const capabilitySummary = capability.scoring === 'observed non-scoring'
      ? `${capability.observed_calls} observed calls · non-scoring · semantic quality claim null`
      : capability.observed_calls === 0
        ? `zero calls · absent recheck ${capability.capability_absent_recheck}`
        : `${capability.observed} · full inputs ${capability.full_semantic_inputs ? 'yes' : 'no'}`;
    const references = task.reference_paths.map((path, index) =>
      `<a href="${sourceUrl(path)}">reference ${index + 1}</a><span>${esc(path)} · ${esc(task.reference_structures[index])}<br><strong>${esc(task.reference_behaviors[index])}</strong><br>witness: ${esc(task.reference_proof_markers[index])}</span>`
    ).join('');
    return `
    <article class="qual-task">
      <div class="qual-task-head">
        <div>
          <div class="chips review-chips">
            <span class="ae-chip">${esc(task.mode)}</span>
            <span class="ae-chip">AI ${esc(task.ai_necessity)}</span>
          </div>
          <h3>${esc(task.task_id)}</h3>
          <p>${esc(task.visible_request)}</p>
        </div>
        <div class="task-reward"><strong>${task.reward.toFixed(1)}</strong><span>oracle reward</span></div>
      </div>
      <p class="seam-note"><span>Declared seam</span>${esc(task.seam_family)}</p>
      <div class="coverage-grid">
        <div class="coverage-block measured-block">
          <p class="coverage-label">Measured · oracle run</p>
          <p><strong>Reference applied; verifier passed.</strong> ${esc(task.verifier_summary)}</p>
          <dl class="mini-receipt mono num">
            <div><dt>trial</dt><dd>${esc(task.trial_name)}</dd></div>
            <div><dt>job</dt><dd>${esc(task.job_id)}</dd></div>
            <div><dt>evidence</dt><dd>${esc(task.evidence_id)}</dd></div>
            <div><dt>task checksum</dt><dd>${esc(task.task_checksum)}</dd></div>
            <div><dt>wall receipt</dt><dd>${(task.latency_ms / 1000).toFixed(3)}s</dd></div>
            <div><dt>semantic receipt</dt><dd>${esc(capabilitySummary)}</dd></div>
            <div><dt>receipt authorship</dt><dd>${esc(capability.candidate_receipt_authorship)}</dd></div>
          </dl>
        </div>
        <div class="coverage-block gate-block">
          <p class="coverage-label">Package gate only · not scored attempts</p>
          <p><strong>2/2 structurally and behaviorally distinct references passed; ${task.mutants.length}/${task.mutants.length} named mutants rejected</strong> for their declared reason.</p>
          <ul class="mutant-list">${task.mutants.map((mutant) => `
            <li><span class="mutant-kill" aria-label="expected failure">×</span><div><code>${esc(mutant.id)}</code><p>${esc(mutant.expected_failure)}</p><small>marker: ${esc(mutant.failure_marker)}</small></div></li>`).join('')}</ul>
        </div>
      </div>
      <div class="task-source-row mono">
        ${references}
        <a href="${sourceUrl(task.verifier_path)}">verifier</a><span>${esc(task.verifier_path)}</span>
      </div>
    </article>`;
  }).join('');

  const ledger = review.evidence_ledger.map((group) => `
    <article class="evidence-card evidence-${esc(group.state)}">
      <p class="evidence-state">${esc(group.state.replaceAll('_', ' '))}</p>
      <h3>${esc(group.label)}</h3>
      <ul>${group.items.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>
    </article>`).join('');

  const readiness = review.readiness_path.map((item) => `
    <li><span class="path-number num">${item.step}</span><div><h3>${esc(item.title)}</h3><p>${esc(item.detail)}</p></div></li>`).join('');

  const findings = review.construct_findings.map((finding) => `
    <article class="blocker-card finding-${esc(finding.status)}">
      <div class="blocker-heading"><span>${esc(finding.status.replaceAll('_', ' '))}</span><code>${esc(finding.id)}</code></div>
      <h3>${esc(finding.title)}</h3>
      <p>${esc(finding.detail)}</p>
      <div class="blocker-sources">${finding.source_paths.map((path) => `<a href="${sourceUrl(path)}">${esc(path)}</a>`).join('')}</div>
    </article>`).join('');

  const sources = review.sources.map((source) => `
    <li><a href="${esc(source.url)}">${esc(source.label)}</a><code>${esc(source.path)}</code></li>`).join('');
  const modeScores = run.mode_scores.map((mode) => `
    <article>
      <p>${esc(mode.mode)}</p>
      <strong class="num">${mode.successes}/${mode.n}</strong>
      <span class="num">95% ${esc(mode.method)} · ${pct(mode.lower)}–${pct(mode.upper)}</span>
      ${mode.interpretation ? `<small>${esc(mode.interpretation)}</small>` : ''}
    </article>`).join('');

  root.innerHTML = `
    <div class="review-hero">
      <a class="backlink" href="./">← all Bench work</a>
      <p class="status-kicker">${esc(review.status.label)} · not a model run</p>
      <h1>${esc(review.title)} <span>${esc(review.subtitle)}</span></h1>
      <p class="review-deck">${esc(review.status.headline)}</p>
      <p class="review-explainer">${esc(review.status.explanation)}</p>
      <div class="boundary-grid">
        <div class="boundary-yes">
          <p>What ran</p>
          <strong>${score.n} task oracle applications</strong>
          <span>Crucible → Harbor → oracle → deterministic verifier; ${review.tasks.length * 2} references package-qualified</span>
        </div>
        <div class="boundary-no">
          <p>What did not run</p>
          <strong>0 model candidates</strong>
          <span>No model, provider, candidate prompt, transcript, or model tokens</span>
        </div>
      </div>
    </div>

    <section aria-labelledby="qualification-result">
      <p class="sect-title" id="qualification-result">Reference qualification result</p>
      <div class="score-layout">
        <div class="score-panel">
          <p class="score-name">Harbor reward pass rate</p>
          <div class="score-big num">${pct(score.point)} <span>${score.successes}/${score.n}</span></div>
          <div class="review-ci" aria-label="95% Wilson interval from ${pct(score.lower)} to ${pct(score.upper)}">
            <div class="review-ci-band" style="left:${score.lower * 100}%;width:${(score.upper - score.lower) * 100}%"></div>
            <div class="review-ci-point" style="left:${score.point * 100}%"></div>
          </div>
          <p class="ci-label num">${score.confidence * 100}% ${esc(score.method)} interval · ${pct(score.lower)}–${pct(score.upper)}</p>
          <p class="score-caution">This is the reference integration rate for ${score.n} public development tasks. Neither the point nor interval estimates model capability, and unlike modes are not pooled into a Seam Agency model score.</p>
          <div class="mode-score-grid">${modeScores}</div>
        </div>
        <div class="usage-panel">
          <p class="usage-title">Model use: none</p>
          <p>${esc(usage.interpretation)}</p>
          <dl class="usage-grid mono num">
            <div><dt>model</dt><dd>${monoValue(run.model)}</dd></div>
            <div><dt>provider</dt><dd>${monoValue(run.provider)}</dd></div>
            <div><dt>raw cost_usd</dt><dd>${monoValue(usage.cost_usd)}</dd></div>
            <div><dt>input tokens</dt><dd>${monoValue(usage.n_input_tokens)}</dd></div>
            <div><dt>output tokens</dt><dd>${monoValue(usage.n_output_tokens)}</dd></div>
            <div><dt>cache tokens</dt><dd>${monoValue(usage.n_cache_tokens)}</dd></div>
          </dl>
          <p class="zero-cost"><strong>Expected economic model cost: $0</strong><span>No inference service was called.</span></p>
        </div>
      </div>
    </section>

    <section aria-labelledby="run-identity">
      <p class="sect-title" id="run-identity">Exact run identity</p>
      <div class="identity-shell scroll">
        <table class="identity-table">
          <tbody>
            <tr><th>run id</th><td>${esc(run.run_id)}</td></tr>
            <tr><th>invocation</th><td>${esc(run.invocation_id)}</td></tr>
            <tr><th>executed</th><td>${esc(executed)}</td></tr>
            <tr><th>benchmark</th><td>${esc(run.benchmark_id)}</td></tr>
            <tr><th>runner / config</th><td>${esc(run.runner_kind)} · ${esc(run.config_id)}</td></tr>
            <tr><th>agent</th><td>${esc(run.agent.name)} ${esc(run.agent.version)} · reference oracle</td></tr>
            <tr><th>repository revision</th><td>${esc(run.repo)}@${esc(run.git_sha)} <span class="muted">(${shortSha(run.git_sha)})</span></td></tr>
            <tr><th>resource envelope</th><td>${run.resource_envelope.cpu_millicores}m CPU · ${run.resource_envelope.memory_mb} MB · ${run.resource_envelope.headroom_percent}% headroom</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section aria-labelledby="materialized-tasks">
      <p class="sect-title" id="materialized-tasks">Seven materialized tasks</p>
      <p class="section-intro">Each task exposes its declared seam, two structurally and behaviorally distinct references with executable witnesses, verifier, runtime capability receipt, and separately qualified wrong-seam mutants.</p>
      <div class="qual-tasks">${tasks}</div>
    </section>

    <section aria-labelledby="evidence-boundary">
      <p class="sect-title" id="evidence-boundary">Evidence boundary</p>
      <p class="section-intro">Four states prevent package qualification from being mistaken for benchmark evidence.</p>
      <div class="evidence-grid">${ledger}</div>
    </section>

    <section aria-labelledby="construct-findings">
      <p class="sect-title" id="construct-findings">Construct hardening and remaining blockers</p>
      <p class="section-intro">Resolved findings are limited to public development construct qualification. Remaining limitations still block a benchmark capability claim.</p>
      <div class="blocker-grid">${findings}</div>
    </section>

    <section aria-labelledby="benchmark-path">
      <p class="sect-title" id="benchmark-path">Concrete path to a usable benchmark</p>
      <ol class="readiness-path">${readiness}</ol>
    </section>

    <section aria-labelledby="checked-sources">
      <p class="sect-title" id="checked-sources">Checked-in sources</p>
      <p class="section-intro">Every claim above comes from the package declarations, the dated sanitized qualification receipt, or the established Crucible oracle evidence captured there.</p>
      <ul class="source-list">${sources}</ul>
    </section>`;
})();
