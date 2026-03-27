const STAGE_COPY = {
  import: {
    title: "Import",
    description: "GitHub 저장소 접근을 확인하고 임시 source workspace를 준비하는 단계입니다.",
  },
  analysis: {
    title: "Analysis",
    description: "저장소 구조를 읽고 인증, 주문, 마운트 후보를 추려내는 단계입니다.",
  },
  planning: {
    title: "Planning",
    description: "어디에 붙일지 결정하고 검증 계획까지 정리하는 단계입니다.",
  },
  compile: {
    title: "Compile",
    description: "수정 파일과 생성 파일을 실제 편집 프로그램으로 바꾸는 단계입니다.",
  },
  apply: {
    title: "Apply",
    description: "워크스페이스에 변경을 적용해 실행 가능한 결과물을 만드는 단계입니다.",
  },
  export: {
    title: "Export",
    description: "적용 결과를 패치로 다시 추출하고 재현 가능한지 확인하는 단계입니다.",
  },
  validation: {
    title: "Validation",
    description: "검증이 끝나면 실제 bilyeo와 챗봇 서버가 올라와 정상 동작 준비가 됩니다.",
  },
};

const state = {
  currentRun: null,
  pollingTimer: null,
  playbackTimer: null,
  config: null,
  selectedStage: "import",
  selectionPinned: false,
  lastPayload: null,
  lastError: null,
  displayStages: [],
  targetStages: [],
};

const LIMITS = {
  cards: 4,
  highlights: 2,
  tags: 3,
  list: 2,
  checks: 2,
  services: 3,
};

const COMPACT_LIMITS = {
  cards: 2,
  highlights: 1,
  tags: 2,
  list: 1,
  checks: 2,
  services: 2,
};

const refs = {
  form: document.getElementById("start-form"),
  githubForm: document.getElementById("github-form"),
  heroStatusText: document.getElementById("hero-status-text"),
  launchButton: document.getElementById("launch-button"),
  githubLaunchButton: document.getElementById("github-launch-button"),
  runMeta: document.getElementById("run-meta"),
  stageTimeline: document.getElementById("stage-timeline"),
  detailTitle: document.getElementById("detail-title"),
  detailStatus: document.getElementById("detail-status"),
  detailDescription: document.getElementById("detail-description"),
  stageDetail: document.getElementById("stage-detail"),
  siteSelect: document.getElementById("site"),
  repoUrlInput: document.getElementById("repo-url"),
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function formValue(id) {
  return document.getElementById(id).value.trim();
}

function setFormValue(id, value) {
  document.getElementById(id).value = value || "";
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function statusClass(status) {
  if (["completed", "exported", "ready"].includes(status)) return "ok";
  if (["running", "starting"].includes(status)) return "warn";
  if (["failed", "process_failed", "failed_human_review", "blocked"].includes(status)) return "fail";
  return "neutral";
}

function limitItems(items, max) {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.filter((item) => item != null).slice(0, max);
}

function viewLimits(compact = false) {
  return compact ? COMPACT_LIMITS : LIMITS;
}

function renderCards(cards = [], limits = LIMITS) {
  const visibleCards = limitItems(cards, limits.cards);
  if (!visibleCards.length) {
    return '<div class="empty-state">표시할 요약 카드가 아직 없습니다.</div>';
  }
  return `<div class="facts-grid">${visibleCards
    .map(
      (card) => `
        <div class="fact-card">
          <span>${escapeHtml(card.label)}</span>
          <strong>${escapeHtml(card.value)}</strong>
          ${card.caption ? `<small>${escapeHtml(card.caption)}</small>` : ""}
        </div>
      `
    )
    .join("")}</div>`;
}

function renderHighlights(items = [], limits = LIMITS) {
  const visibleItems = limitItems(items, limits.highlights);
  if (!visibleItems.length) {
    return "";
  }
  return `<div class="fact-list">${visibleItems
    .map(
      (item) => `
        <div class="fact-list-item">
          <strong>${escapeHtml(item.label)}</strong>
          <small>${escapeHtml(item.value)}</small>
        </div>
      `
    )
    .join("")}</div>`;
}

function renderTags(items = [], limits = LIMITS) {
  const visibleItems = limitItems(items, limits.tags);
  if (!visibleItems.length) {
    return "";
  }
  return `<div class="tag-list">${visibleItems.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>`;
}

function renderList(items = [], formatter, limits = LIMITS) {
  const visibleItems = limitItems(items, limits.list);
  if (!visibleItems.length) {
    return "";
  }
  return `<div class="fact-list">${visibleItems.map((item) => formatter(item)).join("")}</div>`;
}

function renderRunMeta(run, demo = {}) {
  const modeLabel = demo.status === "disabled" ? "mode" : "bilyeo";
  refs.runMeta.innerHTML = `
    <div class="run-summary">
      <span><strong>site</strong><small>${escapeHtml(run.site)}</small></span>
      <span><strong>run</strong><small title="${escapeHtml(run.run_id)}">${escapeHtml(run.run_id)}</small></span>
      <span><strong>status</strong><small>${escapeHtml(run.status_label)}</small></span>
      <span><strong>${escapeHtml(modeLabel)}</strong><small>${escapeHtml(demo.status_label || "Waiting")}</small></span>
    </div>
  `;
}

function renderImport(details = {}, compact = false) {
  const limits = viewLimits(compact);
  const summaryHtml = details.summary
    ? `<div class="fact-list"><div class="fact-list-item"><strong>Summary</strong><small>${escapeHtml(details.summary)}</small></div></div>`
    : "";
  return `
    ${renderCards(details.cards, limits)}
    ${summaryHtml}
  `;
}

function cloneStages(stages = []) {
  return stages.map((stage) => ({ ...stage }));
}

function nextPlaybackStatus(currentStatus, targetStatus) {
  if (currentStatus === targetStatus) {
    return targetStatus;
  }
  if (currentStatus === "pending" && (targetStatus === "completed" || targetStatus === "failed")) {
    return "running";
  }
  if (currentStatus === "pending" && targetStatus === "running") {
    return "running";
  }
  if (currentStatus === "running") {
    return targetStatus;
  }
  return targetStatus;
}

function syncStagePlayback(stages = []) {
  const incomingStages = cloneStages(stages);
  state.targetStages = incomingStages;

  if (!state.displayStages.length) {
    state.displayStages = incomingStages.map((stage) => ({
      ...stage,
      status: "pending",
      status_label: "Waiting",
      summary: "",
    }));
  }

  if (state.playbackTimer) {
    return;
  }

  stepStagePlayback();
}

function stepStagePlayback() {
  const targetStages = state.targetStages || [];
  const displayStages = state.displayStages || [];
  if (!targetStages.length || !displayStages.length) {
    state.playbackTimer = null;
    return;
  }

  const diffIndex = displayStages.findIndex((stage, index) => {
    const target = targetStages[index];
    return Boolean(target) && (stage.status !== target.status || stage.summary !== target.summary);
  });

  if (diffIndex === -1) {
    state.playbackTimer = null;
    renderStageMenu(displayStages);
    if (state.lastPayload) {
      renderSelectedStage(state.lastPayload);
    }
    return;
  }

  const current = displayStages[diffIndex];
  const target = targetStages[diffIndex];
  const nextStatus = nextPlaybackStatus(current.status, target.status);
  displayStages[diffIndex] = {
    ...target,
    status: nextStatus,
    status_label: target.status_label,
    summary: nextStatus === target.status ? target.summary : current.summary,
  };

  if (nextStatus !== target.status) {
    displayStages[diffIndex].status_label = "Running";
  } else {
    displayStages[diffIndex].status_label = target.status_label;
  }

  if (!state.selectionPinned) {
    state.selectedStage = displayStages[diffIndex].stage;
  }

  renderStageMenu(displayStages);
  if (state.lastPayload) {
    renderSelectedStage(state.lastPayload);
  }

  state.playbackTimer = window.setTimeout(() => {
    state.playbackTimer = null;
    stepStagePlayback();
  }, 650);
}

function renderStageMenu(stages = []) {
  refs.stageTimeline.innerHTML = stages
    .map((stage) => {
      const isActive = state.selectedStage === stage.stage;
      const copy = STAGE_COPY[stage.stage] || {};
      return `
        <button type="button" class="stage-link ${isActive ? "active" : ""}" data-stage="${escapeHtml(stage.stage)}">
          <div class="stage-link-head">
            <h3>${escapeHtml(stage.label)}</h3>
            <small>${escapeHtml(stage.status_label)}</small>
          </div>
          <p>${escapeHtml(copy.description || "")}</p>
        </button>
      `;
    })
    .join("");

  refs.stageTimeline.querySelectorAll(".stage-link").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedStage = button.dataset.stage || "analysis";
      state.selectionPinned = true;
      if (state.lastPayload) {
        renderSelectedStage(state.lastPayload);
        renderStageMenu(state.lastPayload.stages || []);
      }
    });
  });
}

function renderAnalysis(details = {}, compact = false) {
  const limits = viewLimits(compact);
  return `
    ${renderCards(details.cards, limits)}
    ${renderHighlights(details.highlights, limits)}
    ${renderTags(details.confidence_notes || [], limits)}
    ${renderList(details.candidates || [], (item) => `
      <div class="fact-list-item">
        <strong>${escapeHtml(item.label)}</strong>
        <small>${escapeHtml(item.path)} / ${escapeHtml(item.reason)}</small>
      </div>
    `, limits)}
  `;
}

function renderPlanning(details = {}, compact = false) {
  const limits = viewLimits(compact);
  return `
    ${renderCards(details.cards, limits)}
    ${renderList(details.target_bindings || [], (item) => `
      <div class="fact-list-item">
        <strong>${escapeHtml(item.capability)}</strong>
        <small>${escapeHtml(item.target_path)} / ${escapeHtml(item.reason)}</small>
      </div>
    `, limits)}
    ${renderList(details.validation_plan || [], (item) => `
      <div class="fact-list-item">
        <strong>${escapeHtml(item.name)}</strong>
        <small>${escapeHtml(item.target)} / ${escapeHtml(item.success_signal)}</small>
      </div>
    `, limits)}
  `;
}

function renderCompile(details = {}, compact = false) {
  const limits = viewLimits(compact);
  return `
    ${renderCards(details.cards, limits)}
    ${renderList(details.host_targets || [], (item) => `
      <div class="fact-list-item">
        <strong>Host</strong>
        <small>${escapeHtml(item)}</small>
      </div>
    `, limits)}
    ${renderList(details.chatbot_targets || [], (item) => `
      <div class="fact-list-item">
        <strong>Chatbot</strong>
        <small>${escapeHtml(item)}</small>
      </div>
    `, limits)}
    ${renderTags((details.operation_mix || []).map((item) => `${item.operation} x${item.count}`), limits)}
  `;
}

function renderApply(details = {}, compact = false) {
  const limits = viewLimits(compact);
  return `
    ${renderCards(details.cards, limits)}
    ${renderHighlights(details.paths || [], limits)}
    ${renderList(details.applied_files || [], (item) => `
      <div class="fact-list-item">
        <strong>Applied file</strong>
        <small>${escapeHtml(item)}</small>
      </div>
    `, limits)}
  `;
}

function renderExport(details = {}, compact = false) {
  const limits = viewLimits(compact);
  return `
    ${renderCards(details.cards, limits)}
    ${renderHighlights(details.paths || [], limits)}
    ${
      details.failure_summary
        ? `<div class="fact-list"><div class="fact-list-item"><strong>Replay note</strong><small>${escapeHtml(details.failure_summary)}</small></div></div>`
        : ""
    }
  `;
}

function renderServiceGrid(services = [], demo = {}, limits = LIMITS) {
  const visibleServices = limitItems(services, limits.services);
  if (!visibleServices.length) {
    return `
      <div class="demo-banner ${statusClass(demo.status || "pending")}">
        <strong>${escapeHtml(demo.status_label || "Waiting for validation")}</strong>
        <small>${escapeHtml(demo.message || "서비스는 validation 이후에 시작됩니다.")}</small>
      </div>
    `;
  }

  return `
    <div class="demo-banner ${statusClass(demo.status || "pending")}">
      <strong>${escapeHtml(demo.status_label || "Bilyeo")}</strong>
      <small>${escapeHtml(demo.message || "")}</small>
    </div>
    <div class="service-grid">
      ${visibleServices
        .map(
          (service) => `
            <div class="service-card">
              <div class="service-card-head">
                <strong>${escapeHtml(service.label)}</strong>
                <span class="status-badge ${statusClass(service.status)}">${escapeHtml(service.status_label)}</span>
              </div>
              <p>${escapeHtml(service.reason || service.url || "")}</p>
              ${
                service.url
                  ? `<a class="service-link" href="${escapeHtml(service.url)}" target="_blank" rel="noreferrer">열기</a>`
                  : ""
              }
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

function renderValidation(details = {}, services = [], demo = {}, compact = false) {
  const limits = viewLimits(compact);
  const checks = limitItems(details.checks || [], limits.checks)
    .map(
      (item) => `
        <div class="check-card">
          <span class="status-badge ${item.passed ? "ok" : "fail"}">${item.passed ? "PASS" : "FAIL"}</span>
          <h4>${escapeHtml(item.name)}</h4>
          <p>${escapeHtml(item.summary)}</p>
        </div>
      `
    )
    .join("");

  const proofLink = demo.preview_url
    ? `<div class="fact-list"><div class="fact-list-item"><strong>Preview</strong><small>${escapeHtml(demo.preview_url)}</small></div></div>`
    : "";

  return `
    ${renderServiceGrid(services, demo, limits)}
    ${renderCards(details.cards, limits)}
    ${renderHighlights(details.proofs || [], limits)}
    ${proofLink}
    <div class="checks-grid">${checks || '<div class="empty-state">검증 체크 결과가 아직 없습니다.</div>'}</div>
  `;
}

function renderRepairInsight(repair = {}) {
  if (!repair.active) {
    return "";
  }

  const tags = [
    repair.failed_stage_label ? `문제 단계: ${repair.failed_stage_label}` : "",
    repair.effective_rewind_label ? `되감기 단계: ${repair.effective_rewind_label}` : "",
    repair.repeat_count ? `반복 횟수: ${repair.repeat_count}회` : "",
  ].filter(Boolean);

  return `
    <div class="repair-banner ${statusClass(repair.status || "pending")}">
      <div class="repair-banner-head">
        <strong>${escapeHtml(repair.status_label || "문제 감지")}</strong>
        <span class="status-badge ${statusClass(repair.status || "pending")}">${escapeHtml(repair.failure_signature || "repair")}</span>
      </div>
      <p>${escapeHtml(repair.problem_explanation || "문제 원인을 분석하고 있습니다.")}</p>
      ${repair.current_action ? `<small>${escapeHtml(repair.current_action)}</small>` : ""}
    </div>
    ${tags.length ? `<div class="tag-list">${tags.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    ${
      repair.diagnosis_summary
        ? `<div class="fact-list"><div class="fact-list-item"><strong>원인 설명</strong><small>${escapeHtml(repair.diagnosis_summary)}</small></div></div>`
        : ""
    }
    ${
      repair.stop_reason_text
        ? `<div class="fact-list"><div class="fact-list-item"><strong>중단 이유</strong><small>${escapeHtml(repair.stop_reason_text)}</small></div></div>`
        : ""
    }
  `;
}

function renderErrorPane(error = null) {
  if (!error) {
    return "";
  }
  return `
    <section class="stage-error-pane">
      <div class="stage-error-head">
        <strong>Error</strong>
        ${error.source ? `<span class="status-badge fail">${escapeHtml(error.source)}</span>` : ""}
      </div>
      <p>${escapeHtml(error.message || "알 수 없는 오류가 발생했습니다.")}</p>
    </section>
  `;
}

function pickDefaultStage(stages = []) {
  const running = stages.find((item) => item.status === "running");
  if (running) return running.stage;
  const failed = [...stages].reverse().find((item) => item.status === "failed");
  if (failed) return failed.stage;
  const completed = [...stages].reverse().find((item) => item.status === "completed");
  return completed ? completed.stage : "analysis";
}

function isTerminalRunStatus(status) {
  return ["exported", "failed", "failed_human_review", "process_failed"].includes(status);
}

function isTerminalDemoStatus(status) {
  return ["ready", "failed", "blocked"].includes(status);
}

function shouldContinuePolling(payload) {
  const processRunning = Boolean((payload.process || {}).running);
  const runStatus = String((payload.run || {}).status || "");
  const demoStatus = String((payload.demo || {}).status || "");

  if (processRunning) {
    return true;
  }
  if (!isTerminalRunStatus(runStatus)) {
    return true;
  }
  if (!demoStatus) {
    return false;
  }
  return !isTerminalDemoStatus(demoStatus);
}

function stopPolling() {
  if (!state.pollingTimer) {
    return;
  }
  window.clearInterval(state.pollingTimer);
  state.pollingTimer = null;
}

function renderSelectedStage(payload) {
  const selected = state.selectedStage;
  const details = payload.details || {};
  const repair = payload.repair || {};
  const stages = (state.displayStages && state.displayStages.length ? state.displayStages : payload.stages) || [];
  const stageView = stages.find((item) => item.stage === selected) || null;
  const copy = STAGE_COPY[selected] || STAGE_COPY.analysis;
  const compactView = Boolean(repair.active || state.lastError);

  refs.detailTitle.textContent = copy.title;
  refs.detailDescription.textContent = copy.description;
  refs.detailStatus.textContent = stageView ? stageView.status_label : "Waiting";
  refs.detailStatus.className = `status-badge ${statusClass(stageView ? stageView.status : "pending")}`;

  let html = "";
  if (selected === "import") html = renderImport(details.import || {}, compactView);
  else if (selected === "analysis") html = renderAnalysis(details.analysis || {}, compactView);
  else if (selected === "planning") html = renderPlanning(details.planning || {}, compactView);
  else if (selected === "compile") html = renderCompile(details.compile || {}, compactView);
  else if (selected === "apply") html = renderApply(details.apply || {}, compactView);
  else if (selected === "export") html = renderExport(details.export || {}, compactView);
  else if (selected === "validation") html = renderValidation(details.validation || {}, payload.services || [], payload.demo || {}, compactView);

  const mainHtml = html
    ? html
    : '<div class="empty-state">이 단계에서 표시할 내용이 아직 없습니다.</div>';
  const repairHtml = renderRepairInsight(repair);
  const errorHtml = renderErrorPane(state.lastError);
  const sideHtml = errorHtml || repairHtml;

  if (sideHtml) {
    refs.stageDetail.classList.add("with-sidepane");
    refs.stageDetail.innerHTML = `
      <div class="stage-detail-main">${mainHtml}</div>
      <div class="stage-detail-error">${sideHtml}</div>
    `;
    return;
  }

  refs.stageDetail.classList.remove("with-sidepane");
  refs.stageDetail.innerHTML = mainHtml;
}

function currentProjectOption() {
  const site = formValue("site");
  return (state.config?.project_options || []).find((item) => item.site === site) || null;
}

async function loadConfig() {
  state.config = await request("/api/config");
  const options = state.config.project_options || [];
  refs.siteSelect.innerHTML = options
    .map((item) => `<option value="${escapeHtml(item.site)}">${escapeHtml(item.site)}</option>`)
    .join("");

  if (options[0]) {
    setFormValue("site", options[0].site);
  }
}

function serializeForm() {
  const selectedProject = currentProjectOption();
  return {
    site: formValue("site"),
    source_root: selectedProject?.source_root || "",
    run_id: selectedProject?.run_id || null,
    generated_root: selectedProject?.generated_root || state.config?.generated_root_default || "generated-v2",
    runtime_root: selectedProject?.runtime_root || state.config?.runtime_root_default || "runtime-v2",
    preview_url: selectedProject?.preview_url || state.config?.preview_url_default || null,
  };
}

function serializeGithubImportForm() {
  return {
    repo_url: formValue("repo-url"),
  };
}

function resetActionButtons() {
  refs.launchButton.disabled = false;
  refs.launchButton.textContent = "프리셋 실행";
  refs.githubLaunchButton.disabled = false;
  refs.githubLaunchButton.textContent = "가져오기";
}

function beginRunTracking(payload, preferredStage = "import") {
  state.currentRun = {
    site: payload.site,
    run_id: payload.run_id,
    generated_root: payload.generated_root || state.config?.generated_root_default || "generated-v2",
  };
  state.selectionPinned = false;
  state.selectedStage = preferredStage;
  state.displayStages = [];
  state.targetStages = [];
  state.lastError = null;
  if (state.playbackTimer) {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
  }
  startPolling();
}

function resolveHeroStatus(payload) {
  const stages = (state.displayStages && state.displayStages.length ? state.displayStages : payload.stages) || [];
  const importStage = stages.find((item) => item.stage === "import");
  if (importStage && ["running", "failed"].includes(importStage.status)) {
    return importStage.status_label;
  }
  if (payload.demo?.status && payload.demo.status !== "disabled") {
    return payload.demo.status_label;
  }
  return payload.run.status_label;
}

function restoreRunFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const site = params.get("site");
  const runId = params.get("run_id");
  if (!site || !runId) {
    return false;
  }
  state.currentRun = {
    site,
    run_id: runId,
    generated_root: params.get("generated_root") || state.config?.generated_root_default || "generated-v2",
  };
  state.selectedStage = "import";
  state.selectionPinned = false;
  const cleanUrl = `${window.location.pathname}${window.location.hash || ""}`;
  window.history.replaceState({}, "", cleanUrl);
  startPolling();
  return true;
}

async function refreshDashboard() {
  if (!state.currentRun) return;

  const query = new URLSearchParams({
    site: state.currentRun.site,
    generated_root: state.currentRun.generated_root,
  });
  const payload = await request(`/api/onboarding/runs/${encodeURIComponent(state.currentRun.run_id)}?${query.toString()}`);
  state.lastPayload = payload;
  state.lastError = null;
  syncStagePlayback(payload.stages || []);

  if (!state.selectionPinned) {
    state.selectedStage = pickDefaultStage(state.displayStages.length ? state.displayStages : payload.stages || []);
  }

  refs.heroStatusText.textContent = resolveHeroStatus(payload);
  renderRunMeta(payload.run, payload.demo || {});
  renderStageMenu(state.displayStages.length ? state.displayStages : payload.stages || []);
  renderSelectedStage(payload);

  const activeStages = state.displayStages.length ? state.displayStages : payload.stages || [];
  const importRunning = activeStages.some((item) => item.stage === "import" && item.status === "running");
  if (!(payload.process || {}).running && !importRunning) {
    resetActionButtons();
  }

  if (!shouldContinuePolling(payload)) {
    stopPolling();
  }
}

function startPolling() {
  stopPolling();
  refreshDashboard().catch(showError);
  state.pollingTimer = window.setInterval(() => {
    refreshDashboard().catch(showError);
  }, 1800);
}

function showError(error) {
  state.lastError = {
    source: "runtime",
    message: error.message || String(error),
  };
  refs.heroStatusText.textContent = "오류";
  if (state.lastPayload) {
    renderSelectedStage(state.lastPayload);
  } else {
    refs.stageDetail.classList.add("with-sidepane");
    refs.stageDetail.innerHTML = `
      <div class="stage-detail-main"><div class="empty-state">실행 이력이 아직 없습니다.</div></div>
      <div class="stage-detail-error">${renderErrorPane(state.lastError)}</div>
    `;
  }
  resetActionButtons();
}

refs.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  refs.launchButton.disabled = true;
  refs.launchButton.textContent = "실행 중";
  refs.heroStatusText.textContent = "온보딩 실행 중";
  state.selectionPinned = false;
  state.selectedStage = "analysis";
  state.displayStages = [];
  state.targetStages = [];
  state.lastError = null;
  if (state.playbackTimer) {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
  }

  try {
    const payload = await request("/api/onboarding/start", {
      method: "POST",
      body: JSON.stringify(serializeForm()),
    });
    beginRunTracking(payload, "analysis");
  } catch (error) {
    showError(error);
  }
});

refs.githubForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  refs.githubLaunchButton.disabled = true;
  refs.githubLaunchButton.textContent = "가져오는 중";
  refs.heroStatusText.textContent = "GitHub 저장소 확인 중";
  state.selectionPinned = false;
  state.selectedStage = "import";
  state.displayStages = [];
  state.targetStages = [];
  state.lastError = null;
  if (state.playbackTimer) {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
  }

  try {
    const payload = await request("/api/onboarding/github/imports", {
      method: "POST",
      body: JSON.stringify(serializeGithubImportForm()),
    });
    if (payload.status === "auth_required" && payload.authorize_url) {
      window.location.assign(payload.authorize_url);
      return;
    }
    beginRunTracking(payload, "import");
  } catch (error) {
    showError(error);
  }
});

function renderInitialStageMenu() {
  state.displayStages = ["import", "analysis", "planning", "compile", "apply", "export", "validation"].map((stage) => ({
      stage,
      label: STAGE_COPY[stage].title,
      status: "pending",
      status_label: "Waiting",
    }));
  renderStageMenu(state.displayStages);
}

async function boot() {
  renderInitialStageMenu();
  try {
    await loadConfig();
    restoreRunFromQuery();
  } catch (error) {
    showError(error);
  }
}

boot();
