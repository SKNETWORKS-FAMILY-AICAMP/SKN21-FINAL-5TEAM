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
  rawLogOpen: false,
};

const ACTIVE_RUN_STORAGE_KEY = "onmo.active-run";

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

const REPAIR_LIMITS = {
  cards: 2,
  highlights: 1,
  tags: 1,
  list: 1,
  checks: 1,
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

function storage() {
  try {
    return window.sessionStorage || null;
  } catch (_error) {
    return null;
  }
}

function readStoredJson(key) {
  const activeStorage = storage();
  if (!activeStorage || !key) {
    return null;
  }
  try {
    const raw = activeStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (_error) {
    return null;
  }
}

function writeStoredJson(key, value) {
  const activeStorage = storage();
  if (!activeStorage || !key) {
    return;
  }
  try {
    activeStorage.setItem(key, JSON.stringify(value));
  } catch (_error) {
    // Ignore storage write failures and continue with in-memory state.
  }
}

function runUiStateKey(run = state.currentRun) {
  const site = String(run?.site || "").trim();
  const runId = String(run?.run_id || "").trim();
  if (!site || !runId) {
    return "";
  }
  return `onmo.run-ui:${site}:${runId}`;
}

function syncRunLocation(run = state.currentRun) {
  if (!run || !window.history?.replaceState) {
    return;
  }
  const params = new URLSearchParams();
  params.set("site", run.site);
  params.set("run_id", run.run_id);
  params.set("generated_root", run.generated_root || state.config?.generated_root_default || "generated-v2");
  const search = params.toString();
  const nextUrl = `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash || ""}`;
  window.history.replaceState({}, "", nextUrl);
}

function persistRunContext(run = state.currentRun) {
  if (!run) {
    return;
  }
  writeStoredJson(ACTIVE_RUN_STORAGE_KEY, {
    site: run.site,
    run_id: run.run_id,
    generated_root: run.generated_root || state.config?.generated_root_default || "generated-v2",
  });
  syncRunLocation(run);
}

function persistRunUiState() {
  const key = runUiStateKey();
  if (!key) {
    return;
  }
  writeStoredJson(key, {
    selectedStage: state.selectedStage,
    selectionPinned: Boolean(state.selectionPinned),
    rawLogOpen: Boolean(state.rawLogOpen),
  });
}

function restoreRunUiState(run = state.currentRun) {
  const key = runUiStateKey(run);
  const stored = readStoredJson(key) || {};
  if (typeof stored.selectedStage === "string" && stored.selectedStage.trim()) {
    state.selectedStage = stored.selectedStage;
  }
  state.selectionPinned = Boolean(stored.selectionPinned);
  state.rawLogOpen = Boolean(stored.rawLogOpen);
}

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
  if (compact === "repair") {
    return REPAIR_LIMITS;
  }
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

function renderRunMeta(run, demo = {}, repairStory = {}, repair = {}) {
  const modeLabel = demo.status === "disabled" ? "mode" : "bilyeo";
  const failedLabel = repairStory.failed_stage_label || repair.failed_stage_label || repairStory.failed_stage || "";
  const rewindLabel = repairStory.rewind_to_label || repair.effective_rewind_label || repairStory.rewind_to || "";
  const repairMeta = repairStory.active
    ? `
      <div class="run-repair-meta">
        <div class="run-repair-pill fail">
          <span>Failed Here</span>
          <strong>${escapeHtml(failedLabel || "-")}</strong>
        </div>
        <div class="run-repair-pill rewind">
          <span>Re-enter Here</span>
          <strong>${escapeHtml(rewindLabel || "-")}</strong>
        </div>
        <small>${escapeHtml(repairStory.current_action || repair.current_action || repairStory.summary || "자동 복구 흐름을 정리하는 중입니다.")}</small>
      </div>
    `
    : "";
  refs.runMeta.innerHTML = `
    <div class="run-summary">
      <span><strong>site</strong><small>${escapeHtml(run.site)}</small></span>
      <span><strong>run</strong><small title="${escapeHtml(run.run_id)}">${escapeHtml(run.run_id)}</small></span>
      <span><strong>status</strong><small>${escapeHtml(run.status_label)}</small></span>
      <span><strong>${escapeHtml(modeLabel)}</strong><small>${escapeHtml(demo.status_label || "Waiting")}</small></span>
    </div>
    ${repairMeta}
  `;
}

function formatTimestamp(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return raw;
  }
  return parsed.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function stageFlag(stage) {
  const repairStory = state.lastPayload?.repair_story || {};
  if (repairStory.active && repairStory.failed_stage && repairStory.failed_stage === stage.stage) {
    return { label: "failed here", className: "fail" };
  }
  if (repairStory.active && repairStory.rewind_to && repairStory.rewind_to === stage.stage) {
    return { label: "re-enter here", className: "rewind" };
  }
  if (stage.status === "failed") {
    return { label: "fail", className: "fail" };
  }
  return null;
}

function renderStoryStrip(story = {}) {
  const steps = Array.isArray(story.steps) ? story.steps : [];
  if (!steps.length) {
    return "";
  }
  return `
    <section class="story-section">
      <div class="story-section-head">
        <span class="section-kicker">Run Story</span>
        <small>${escapeHtml(story.headline || "")}</small>
      </div>
      <div class="story-strip">
        ${steps
          .map(
            (step, index) => `
              <div class="story-step ${statusClass(step.status)} ${escapeHtml(step.emphasis || "default")}">
                <div class="story-step-node"></div>
                <div class="story-step-copy">
                  <strong>${escapeHtml(step.label)}</strong>
                  <small>${escapeHtml(step.status_label)}</small>
                </div>
                ${index < steps.length - 1 ? '<div class="story-step-line"></div>' : ""}
              </div>
            `
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderRunStorySnapshot(story = {}) {
  const content = renderStoryStrip(story);
  if (!content) {
    return "";
  }
  return `
    <section class="story-section raw-log-shell">
      <details class="raw-log-panel story-snapshot-panel">
        <summary>
          <span>Run Story Snapshot</span>
          <small>${escapeHtml(story.headline || "전체 단계 흐름")}</small>
        </summary>
        <div class="raw-log-body">
          ${content}
        </div>
      </details>
    </section>
  `;
}

function renderCompactRetrievalSummary(retrieval = {}) {
  if (!retrieval.active) {
    return "";
  }
  const items = Array.isArray(retrieval.items) ? retrieval.items : [];
  const summary = items
    .map((item) => `${item.label || item.corpus || ""} ${item.status_label || item.status || ""}`.trim())
    .filter(Boolean)
    .join(" / ");
  return `
    <div class="repair-retrieval-strip">
      <span>Retrieval</span>
      <small>${escapeHtml(summary || retrieval.summary || "retrieval 준비 상태를 확인하는 중입니다.")}</small>
    </div>
  `;
}

function renderNarrativeSummary(story = {}) {
  if (!story.headline && !story.summary) {
    return "";
  }
  return `
    <section class="story-section story-summary-card">
      <span class="section-kicker">Narrative Summary</span>
      <strong>${escapeHtml(story.headline || "현재 실행 흐름을 확인하는 중입니다.")}</strong>
      <p>${escapeHtml(story.summary || "단계별 진행과 되감기 여부를 정리하는 중입니다.")}</p>
    </section>
  `;
}

function renderRetrievalLane(retrieval = {}) {
  if (!retrieval.active) {
    return "";
  }
  const items = Array.isArray(retrieval.items) ? retrieval.items : [];
  return `
    <section class="story-section retrieval-section">
      <div class="story-section-head">
        <span class="section-kicker">${escapeHtml(retrieval.headline || "Retrieval Ready")}</span>
        <small>${escapeHtml(retrieval.summary || "")}</small>
      </div>
      <div class="retrieval-chip-list">
        ${items
          .map(
            (item) => `
              <div class="retrieval-chip ${escapeHtml(item.status || "queued")}">
                <strong>${escapeHtml(item.label || item.corpus || "")}</strong>
                <small>${escapeHtml(item.status_label || "")}</small>
              </div>
            `
          )
          .join("")}
      </div>
      ${
        retrieval.rewind_note
          ? `<p class="section-note">${escapeHtml(retrieval.rewind_note)}</p>`
          : ""
      }
    </section>
  `;
}

function renderRepairStory(repairStory = {}, repair = {}, options = {}) {
  if (!repairStory.active) {
    return "";
  }
  const focusTitle = options.focusTitle || "Focus";
  const focusHtml = options.focusHtml || '<div class="empty-state">표시할 세부 내용이 없습니다.</div>';
  const retrieval = options.retrieval || {};
  const steps = Array.isArray(repairStory.steps) ? repairStory.steps : [];
  const failedLabel = repairStory.failed_stage_label || repair.failed_stage_label || repairStory.failed_stage || "-";
  const rewindLabel = repairStory.rewind_to_label || repair.effective_rewind_label || repairStory.rewind_to || "-";
  const diagnosis = repairStory.diagnosis || repair.diagnosis_summary || "원인을 분석 중입니다.";
  const currentAction = repairStory.current_action || repair.current_action || repair.stop_reason_text || "재실행 단계를 준비 중입니다.";
  const problem = repairStory.problem || repair.problem_explanation || repair.failure_summary || repairStory.summary || "문제 원인을 정리하는 중입니다.";
  const statusLabel = repairStory.status_label || repair.status_label || "Repair Running";
  return `
    <section class="story-section rewind-section primary-rewind repair-hero">
      <div class="story-section-head repair-hero-head">
        <div class="repair-head-copy repair-hero-copy">
          <span class="section-kicker">${escapeHtml(repairStory.headline || "Repair Rewind")}</span>
          <strong>${escapeHtml(failedLabel)} -> ${escapeHtml(rewindLabel)}</strong>
        </div>
        <span class="status-badge ${statusClass(repair.status || "running")}">${escapeHtml(statusLabel)}</span>
      </div>
      <p class="repair-summary-text">${escapeHtml(problem)}</p>
      <p class="repair-now-text">${escapeHtml(currentAction)}</p>
      <div class="repair-sequence repair-hero-sequence">
        ${steps
          .map(
            (step, index) => `
              <div class="repair-sequence-step ${statusClass(step.status)}">
                <div class="repair-sequence-count">${index + 1}</div>
                <div class="repair-sequence-copy">
                  <span>${escapeHtml(step.kind)}</span>
                  <strong>${escapeHtml(step.label)}</strong>
                  <small>${
                    step.timestamp
                      ? escapeHtml(formatTimestamp(step.timestamp))
                      : escapeHtml(step.status || "")
                  }</small>
                </div>
              </div>
            `
          )
          .join("")}
      </div>
      <div class="repair-narrative-stack">
        <div class="repair-narrative-row fail">
          <span>Why It Failed</span>
          <strong>${escapeHtml(diagnosis)}</strong>
          <small>${escapeHtml(problem)}</small>
        </div>
        <div class="repair-narrative-row rewind">
          <span>Re-enter Here</span>
          <strong>${escapeHtml(rewindLabel)}</strong>
          <small>${escapeHtml(repairStory.summary || "실패 지점 앞단부터 다시 확인합니다.")}</small>
        </div>
        <div class="repair-narrative-row current">
          <span>Now Running</span>
          <strong>${escapeHtml(currentAction)}</strong>
          <small>${escapeHtml(steps[steps.length - 1]?.label || "재실행 준비 중")}</small>
        </div>
      </div>
      ${renderCompactRetrievalSummary(retrieval)}
      <div class="repair-focus-shell">
        <div class="repair-focus-head">
          <span class="section-kicker">Repair Focus Detail</span>
          <small>${escapeHtml(focusTitle)}</small>
        </div>
        <div class="repair-focus-body">
          ${focusHtml}
        </div>
      </div>
    </section>
  `;
}

function renderRawEventLog(payload) {
  const events = Array.isArray(payload.recent_events) ? payload.recent_events : [];
  const logPath = payload.process?.log_path || "";
  return `
    <section class="story-section raw-log-shell">
      <details class="raw-log-panel" data-raw-log-panel ${state.rawLogOpen ? "open" : ""}>
        <summary>
          <span>Raw Event Log</span>
          <small>${events.length ? `최근 이벤트 ${events.length}개` : "최근 이벤트 없음"}</small>
        </summary>
        <div class="raw-log-body">
          ${
            logPath
              ? `<div class="raw-log-meta"><strong>Log Path</strong><small>${escapeHtml(logPath)}</small></div>`
              : ""
          }
          ${
            events.length
              ? `<div class="raw-log-list">
                  ${events
                    .map(
                      (event) => `
                        <div class="raw-log-row">
                          <span>${escapeHtml(formatTimestamp(event.timestamp))}</span>
                          <strong>${escapeHtml(event.stage || "-")}</strong>
                          <small>${escapeHtml(event.summary || event.event_type || "-")}</small>
                        </div>
                      `
                    )
                    .join("")}
                </div>`
              : '<div class="empty-state">표시할 최근 이벤트가 아직 없습니다.</div>'
          }
        </div>
      </details>
    </section>
  `;
}

function bindStoryInteractions() {
  const rawPanel = refs.stageDetail.querySelector("[data-raw-log-panel]");
  if (!rawPanel) {
    return;
  }
  rawPanel.addEventListener("toggle", () => {
    state.rawLogOpen = rawPanel.open;
    persistRunUiState();
  });
}

function wrapStageDetail(title, html, kicker = "Current Stage Detail") {
  return `
    <section class="story-section current-stage-section">
      <div class="story-section-head">
        <span class="section-kicker">${escapeHtml(kicker)}</span>
        <small>${escapeHtml(title)}</small>
      </div>
      <div class="current-stage-body">
        ${html}
      </div>
    </section>
  `;
}

function renderStageDetailContent(stageKey, details, payload, compact = true) {
  if (stageKey === "import") return renderImport(details.import || {}, compact);
  if (stageKey === "analysis") return renderAnalysis(details.analysis || {}, compact);
  if (stageKey === "planning") return renderPlanning(details.planning || {}, compact);
  if (stageKey === "compile") return renderCompile(details.compile || {}, compact);
  if (stageKey === "apply") return renderApply(details.apply || {}, compact);
  if (stageKey === "export") return renderExport(details.export || {}, compact);
  if (stageKey === "validation") return renderValidation(details.validation || {}, payload.services || [], payload.demo || {}, compact);
  return "";
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
    state.selectedStage = state.lastPayload?.repair_story?.active
      ? pickDefaultStage(displayStages, state.lastPayload)
      : displayStages[diffIndex].stage;
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
  const repairStory = state.lastPayload?.repair_story || {};
  refs.stageTimeline.innerHTML = stages
    .map((stage) => {
      const isActive = state.selectedStage === stage.stage;
      const copy = STAGE_COPY[stage.stage] || {};
      const flag = stageFlag(stage);
      const muted = repairStory.active && !flag ? "stage-link-muted" : "";
      const anchor = flag ? `anchor-${escapeHtml(flag.className)}` : "";
      return `
        <button type="button" class="stage-link ${isActive ? "active" : ""} ${muted} ${anchor} ${flag ? `marker-${escapeHtml(flag.className)}` : ""}" data-stage="${escapeHtml(stage.stage)}">
          <div class="stage-link-head">
            <h3>${escapeHtml(stage.label)}</h3>
            <div class="stage-link-meta">
              ${flag ? `<span class="stage-mini-flag ${escapeHtml(flag.className)}">${escapeHtml(flag.label)}</span>` : ""}
              <small>${escapeHtml(stage.status_label)}</small>
            </div>
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
      persistRunUiState();
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

function pickDefaultStage(stages = [], payload = state.lastPayload) {
  const repairRewind = String((payload?.repair_story || {}).rewind_to || "");
  if (repairRewind) return repairRewind;
  const storyFocus = String((payload?.story || {}).focus_stage?.stage || "");
  if (storyFocus) return storyFocus;
  const storyCurrent = String((payload?.story || {}).current_stage?.stage || "");
  if (storyCurrent) return storyCurrent;
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
  const stages = (state.displayStages && state.displayStages.length ? state.displayStages : payload.stages) || [];
  const stageView = stages.find((item) => item.stage === selected) || null;
  const story = payload.story || {};
  const repairStory = payload.repair_story || {};
  const repair = payload.repair || {};
  const focusStage = story.focus_stage || story.current_stage || {};
  const failedLabel = repairStory.failed_stage_label || repair.failed_stage_label || repairStory.failed_stage || "";
  const rewindLabel = repairStory.rewind_to_label || repair.effective_rewind_label || repairStory.rewind_to || "";
  const detailStageKey = repairStory.active ? String(focusStage.stage || selected || "analysis") : selected;
  const copy = STAGE_COPY[detailStageKey] || STAGE_COPY.analysis;
  const panelStatus = repairStory.active
    ? {
        label: repair.status_label || payload.run.status_label,
        status: repair.status || payload.run.status,
      }
    : {
        label: story.current_stage?.status_label || payload.run.status_label || (stageView ? stageView.status_label : "Waiting"),
        status: story.current_stage?.status || payload.run.status || (stageView ? stageView.status : "pending"),
      };

  refs.detailTitle.textContent = repairStory.active ? `${failedLabel || "Failure"} -> ${rewindLabel || "Rewind"}` : "Run Story";
  refs.detailDescription.textContent = repairStory.active
    ? `${repairStory.problem || repair.problem_explanation || repairStory.summary || story.headline || ""} ${repairStory.current_action || repair.current_action || ""}`.trim()
    : story.headline || copy.description;
  refs.detailStatus.textContent = panelStatus.label || "Waiting";
  refs.detailStatus.className = `status-badge ${statusClass(panelStatus.status || "pending")}`;

  const html = renderStageDetailContent(detailStageKey, details, payload, repairStory.active ? "repair" : true);

  const stageDetailSection = wrapStageDetail(
    focusStage.label || copy.title,
    html || '<div class="empty-state">이 단계에서 표시할 내용이 아직 없습니다.</div>',
    repairStory.active ? "Repair Focus Detail" : "Current Stage Detail"
  );

  refs.stageDetail.classList.remove("with-sidepane");
  refs.stageDetail.innerHTML = repairStory.active
    ? `
      <div class="story-panel repair-mode">
        ${renderRepairStory(repairStory, repair, {
          focusTitle: focusStage.label || copy.title,
          focusHtml: html || '<div class="empty-state">이 단계에서 표시할 내용이 아직 없습니다.</div>',
          retrieval: story.retrieval || {},
        })}
        ${state.lastError ? renderErrorPane(state.lastError) : ""}
        ${renderRunStorySnapshot(story)}
        ${renderRawEventLog(payload)}
      </div>
    `
    : `
      <div class="story-panel">
        ${renderStoryStrip(story)}
        ${renderNarrativeSummary(story)}
        ${state.lastError ? renderErrorPane(state.lastError) : ""}
        ${stageDetailSection}
        ${renderRetrievalLane(story.retrieval || {})}
        ${renderRawEventLog(payload)}
      </div>
    `;
  bindStoryInteractions();
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
  state.rawLogOpen = false;
  if (state.playbackTimer) {
    window.clearTimeout(state.playbackTimer);
    state.playbackTimer = null;
  }
  persistRunContext();
  persistRunUiState();
  startPolling();
}

function resolveHeroStatus(payload) {
  const stages = (state.displayStages && state.displayStages.length ? state.displayStages : payload.stages) || [];
  const importStage = stages.find((item) => item.stage === "import");
  if (importStage && ["running", "failed"].includes(importStage.status)) {
    return importStage.status_label;
  }
  if (payload.repair_story?.active) {
    return payload.repair?.status_label || payload.run.status_label;
  }
  if (payload.demo?.status && payload.demo.status !== "disabled") {
    return payload.demo.status_label;
  }
  return payload.run.status_label;
}

function restoreRunFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const persistedRun = readStoredJson(ACTIVE_RUN_STORAGE_KEY) || {};
  const site = params.get("site") || persistedRun.site || "";
  const runId = params.get("run_id") || persistedRun.run_id || "";
  if (!site || !runId) {
    return false;
  }
  state.currentRun = {
    site,
    run_id: runId,
    generated_root:
      params.get("generated_root")
      || persistedRun.generated_root
      || state.config?.generated_root_default
      || "generated-v2",
  };
  state.selectedStage = "import";
  restoreRunUiState(state.currentRun);
  persistRunContext();
  persistRunUiState();
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
    state.selectedStage = pickDefaultStage(state.displayStages.length ? state.displayStages : payload.stages || [], payload);
  }
  persistRunUiState();

  refs.heroStatusText.textContent = resolveHeroStatus(payload);
  renderRunMeta(payload.run, payload.demo || {}, payload.repair_story || {}, payload.repair || {});
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
