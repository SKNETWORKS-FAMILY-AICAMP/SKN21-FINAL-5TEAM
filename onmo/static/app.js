const STAGE_COPY = {
  import: {
    title: "가져오기",
    description: "GitHub 저장소 접근을 확인하고 임시 source workspace를 준비하는 단계입니다.",
  },
  analysis: {
    title: "분석",
    description: "저장소 구조를 읽고 인증, 주문, 마운트 후보를 추려내는 단계입니다.",
  },
  planning: {
    title: "계획",
    description: "어디에 붙일지 결정하고 검증 계획까지 정리하는 단계입니다.",
  },
  compile: {
    title: "생성",
    description: "수정 파일과 생성 파일을 실제 편집 프로그램으로 바꾸는 단계입니다.",
  },
  apply: {
    title: "적용",
    description: "워크스페이스에 변경을 적용해 실행 가능한 결과물을 만드는 단계입니다.",
  },
  export: {
    title: "추출",
    description: "적용 결과를 패치로 다시 추출하고 재현 가능한지 확인하는 단계입니다.",
  },
  indexing: {
    title: "인덱싱",
    description: "retrieval corpus를 준비하고 smoke 결과를 확인하는 단계입니다.",
  },
  validation: {
    title: "검증",
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
  rawLogScrollTop: 0,
  rawLogAutoFollow: true,
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
  runStoryShell: document.getElementById("run-story-shell"),
  launchButton: document.getElementById("launch-button"),
  githubLaunchButton: document.getElementById("github-launch-button"),
  stageTimeline: document.getElementById("stage-timeline"),
  detailTitle: document.getElementById("detail-title"),
  detailStatus: document.getElementById("detail-status"),
  detailDescription: document.getElementById("detail-description"),
  stageDetail: document.getElementById("stage-detail"),
  siteSelect: document.getElementById("site"),
  repoUrlInput: document.getElementById("repo-url"),
  githubEnvFileInput: document.getElementById("github-env-file"),
  githubEnvTargetSelect: document.getElementById("github-env-target"),
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
    rawLogScrollTop: Math.max(0, Number(state.rawLogScrollTop) || 0),
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
  state.rawLogScrollTop = Math.max(0, Number(stored.rawLogScrollTop) || 0);
  state.rawLogAutoFollow = state.rawLogScrollTop === 0;
}

async function request(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
  };
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!isFormData && !Object.keys(headers).some((key) => key.toLowerCase() === "content-type")) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {
    headers,
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function formValue(id) {
  const element = document.getElementById(id);
  return typeof element?.value === "string" ? element.value.trim() : "";
}

function setFormValue(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.value = value || "";
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function stageLabel(stageKey, fallback = "") {
  return STAGE_COPY[String(stageKey || "").trim()]?.title || fallback || String(stageKey || "").trim();
}

function localizeUiText(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }

  const replacements = [
    [/Import/g, "가져오기"],
    [/Analysis/g, "분석"],
    [/Planning/g, "계획"],
    [/Compile/g, "생성"],
    [/Apply/g, "적용"],
    [/Export/g, "추출"],
    [/Indexing/g, "인덱싱"],
    [/Validation/g, "검증"],
    [/GitHub Mode/g, "GitHub 모드"],
    [/Running/g, "진행 중"],
    [/Completed/g, "완료"],
    [/Failed/g, "실패"],
    [/Waiting/g, "대기"],
    [/Ready/g, "준비 완료"],
    [/blocked/gi, "중단됨"],
    [/running/gi, "진행 중"],
    [/completed/gi, "완료"],
    [/failed/gi, "실패"],
    [/waiting/gi, "대기"],
    [/ready/gi, "준비 완료"],
  ];

  return replacements.reduce((text, [pattern, next]) => text.replace(pattern, next), raw);
}

function compactText(value, max = 120) {
  const text = localizeUiText(value);
  if (!text || text.length <= max) {
    return text;
  }
  return `${text.slice(0, max - 1).trimEnd()}…`;
}

function describeLivePhase(live = {}) {
  const phaseLabel = localizeUiText(live.phase_label || "");
  if (!phaseLabel) {
    return "";
  }
  if (live.status === "fallback") {
    return `${phaseLabel} fallback 사용`;
  }
  if (live.status === "failed") {
    return `${phaseLabel} 실패`;
  }
  if (live.status === "completed") {
    return `${phaseLabel} 완료`;
  }
  return `${phaseLabel} 진행 중`;
}

function livePhaseHeading(live = {}) {
  const phaseLabel = localizeUiText(live.phase_label || "");
  if (!phaseLabel) {
    return "";
  }
  if (live.status === "fallback") {
    return `${phaseLabel} · fallback 사용`;
  }
  if (live.status === "failed") {
    return `${phaseLabel} · 실패`;
  }
  if (live.status === "completed") {
    return `${phaseLabel} · 완료`;
  }
  return `${phaseLabel} · 진행`;
}

function formatElapsedMs(value) {
  const ms = Number(value);
  if (!Number.isFinite(ms) || ms <= 0) {
    return "";
  }
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}초`;
  }
  return `${Math.round(ms)}ms`;
}

function renderInlineMetrics(metrics = []) {
  const items = Array.isArray(metrics) ? metrics.filter((item) => item && item.label && item.value) : [];
  if (!items.length) {
    return "";
  }
  return `
    <div class="stage-live-metrics">
      ${items
        .map(
          (item) => `
            <span class="stage-live-metric">
              <strong>${escapeHtml(localizeUiText(item.label))}</strong>
              <small>${escapeHtml(localizeUiText(item.value))}</small>
            </span>
          `
        )
        .join("")}
    </div>
  `;
}

function renderLiveEvents(live = {}) {
  const phaseText = describeLivePhase(live);
  const events = Array.isArray(live.events) ? live.events : [];
  const visibleEvents = events.filter((event) => {
    const summary = localizeUiText(event.display_summary || event.summary || "");
    return summary && summary !== phaseText;
  });
  if (!visibleEvents.length) {
    return "";
  }
  return `
    <div class="stage-live-events">
      ${visibleEvents
        .map(
          (event) => `
            <div class="stage-live-event">
              <span>${escapeHtml(formatTimestamp(event.timestamp))}</span>
              <small>${escapeHtml(localizeUiText(event.display_summary || event.summary || ""))}</small>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

function renderLiveTechnicalDetail(live = {}) {
  const meta = [
    live.provider ? `모델 공급자: ${localizeUiText(live.provider)}` : "",
    live.model ? `모델: ${localizeUiText(live.model)}` : "",
    live.attempt ? `시도: ${escapeHtml(String(live.attempt))}` : "",
    formatElapsedMs(live.elapsed_ms) ? `경과: ${formatElapsedMs(live.elapsed_ms)}` : "",
  ].filter(Boolean);
  const issue = compactText(live.issue || "", 180);
  if (!meta.length && !issue) {
    return "";
  }
  return `
    <details class="stage-live-tech">
      <summary>기술 상세</summary>
      ${meta.length ? `<small>${escapeHtml(meta.join(" / "))}</small>` : ""}
      ${issue ? `<p>${escapeHtml(issue)}</p>` : ""}
    </details>
  `;
}

function renderLiveStagePanel(live = {}) {
  if (!live.active_phase) {
    return "";
  }
  return `
    <section class="stage-live-shell">
      <div class="stage-live-head">
        <span>${escapeHtml(livePhaseHeading(live))}</span>
        ${live.issue ? `<small>${escapeHtml(compactText(live.issue, 110))}</small>` : ""}
      </div>
      ${renderInlineMetrics(live.metrics || [])}
      ${renderLiveEvents(live)}
      ${renderLiveTechnicalDetail(live)}
    </section>
  `;
}

function renderRawLogMeta(event = {}) {
  const bits = [
    event.phase_label ? localizeUiText(event.phase_label) : "",
    event.details?.status ? localizeUiText(event.details.status) : "",
    Number.isFinite(Number(event.details?.tool_call_count)) ? `도구 ${event.details.tool_call_count}회` : "",
    event.details?.fallback_reason ? compactText(event.details.fallback_reason, 90) : "",
  ].filter(Boolean);
  return bits.join(" / ");
}

function rawLogMaxScrollTop(element) {
  if (!element) {
    return 0;
  }
  const scrollHeight = Math.max(0, Number(element.scrollHeight) || 0);
  const clientHeight = Math.max(0, Number(element.clientHeight) || 0);
  return Math.max(0, scrollHeight - clientHeight);
}

function rawLogNearBottom(element, threshold = 24) {
  if (!element) {
    return true;
  }
  const scrollTop = Math.max(0, Number(element.scrollTop) || 0);
  return rawLogMaxScrollTop(element) - scrollTop <= threshold;
}

function statusClass(status) {
  if (["completed", "exported", "ready", "passed"].includes(status)) return "ok";
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
    return { label: "오류 지점", className: "fail" };
  }
  if (repairStory.active && repairStory.rewind_to && repairStory.rewind_to === stage.stage) {
    return { label: "되돌아감", className: "rewind" };
  }
  if (stage.status === "failed") {
    return { label: "실패", className: "fail" };
  }
  return null;
}

function resolveLiveStage(payload = state.lastPayload, stages = []) {
  const repairStory = payload?.repair_story || {};
  if (repairStory.active && repairStory.rewind_to) {
    return repairStory.rewind_to;
  }
  if (["running", "starting"].includes(String(payload?.story?.current_stage?.status || "").trim()) && payload?.story?.current_stage?.stage) {
    return payload.story.current_stage.stage;
  }
  const activeStages = Array.isArray(stages) ? stages : [];
  const running = activeStages.find((item) => item.status === "running");
  return running?.stage || "";
}

function statusLabelForStep(status, fallback = "") {
  if (fallback) {
    return localizeUiText(fallback);
  }
  if (status === "completed" || status === "exported" || status === "ready") {
    return "완료";
  }
  if (status === "running" || status === "starting") {
    return "진행 중";
  }
  if (status === "failed" || status === "process_failed" || status === "failed_human_review" || status === "blocked") {
    return "실패";
  }
  return "대기";
}

function shortRepairStatusLabel(repair = {}) {
  const status = String(repair.status || "").trim();
  if (status === "failed") {
    return "중단됨";
  }
  if (status === "running") {
    return "복구 중";
  }
  return localizeUiText(repair.status_label || "대기");
}

function repairStepTimestamp(steps = [], kind = "") {
  const match = Array.isArray(steps)
    ? steps.find((step) => String(step.kind || "").trim() === String(kind || "").trim())
    : null;
  return match?.timestamp || "";
}

function fallbackRepairSummaryCards(repairStory = {}, repair = {}) {
  const steps = Array.isArray(repairStory.steps) ? repairStory.steps : [];
  const failedLabel = localizeUiText(repairStory.failed_stage_label || repair.failed_stage_label || repairStory.failed_stage || "오류 지점");
  const rewindLabel = localizeUiText(repairStory.rewind_to_label || repair.effective_rewind_label || repairStory.rewind_to || "-");
  const problemDetail = localizeUiText(repairStory.problem || repair.problem_explanation || repair.failure_summary || "문제가 발생했습니다.");
  const errorHeadline = localizeUiText(repair.failure_signature || repairStory.failure_signature || repair.failure_summary || repairStory.failure_summary || "-");
  const diagnosisText = localizeUiText(repairStory.diagnosis || repair.diagnosis_summary || "원인을 분석 중입니다.");
  const rewindDetail = localizeUiText(repairStory.current_action || repair.current_action || `${rewindLabel} 단계로 되돌아갑니다.`);
  return [
    {
      key: "failure",
      title: "문제 발생",
      headline: failedLabel || "-",
      detail: `${failedLabel || "오류 지점"} 실패 감지`,
      timestamp: repairStepTimestamp(steps, "failure"),
    },
    {
      key: "error",
      title: "오류 상세",
      headline: errorHeadline,
      detail: problemDetail,
      timestamp: repairStepTimestamp(steps, "failure"),
    },
    {
      key: "diagnosis",
      title: "진단 판단",
      headline: diagnosisText,
      detail: diagnosisText,
      timestamp: repairStepTimestamp(steps, "diagnosis"),
    },
    {
      key: "rewind",
      title: "되돌아감",
      headline: rewindLabel ? `${rewindLabel} 단계` : "-",
      detail: rewindLabel ? `${rewindLabel} 단계로 되돌리기로 결정했습니다.` : rewindDetail,
      timestamp: repairStepTimestamp(steps, "rewind"),
    },
  ];
}

function renderStoryLane(title, subtitle, steps, laneClass = "") {
  if (!Array.isArray(steps) || !steps.length) {
    return "";
  }
  return `
    <div class="story-lane ${laneClass}">
      ${title || subtitle ? `
      <div class="story-lane-head">
        ${title ? `<span>${escapeHtml(title)}</span>` : ""}
        ${subtitle ? `<small>${escapeHtml(subtitle)}</small>` : ""}
      </div>` : ""}
      <div class="story-strip ${laneClass}">
        ${steps
          .map(
            (step, index) => `
              ${step?.placeholder ? '<div class="story-step story-step-placeholder" aria-hidden="true"></div>' : `
              <div class="story-step ${statusClass(step.status)} ${escapeHtml(step.emphasis || "default")}">
                ${step.entry ? `
                  <div class="story-rerun-entry-link">
                    <span class="story-rerun-entry-tag">repair</span>
                    <small>${escapeHtml(localizeUiText(step.entry_label || ""))}</small>
                    <span class="story-rerun-entry-arrow">↓</span>
                  </div>
                ` : ""}
                <div class="story-step-node"></div>
                <div class="story-step-copy">
                  <strong>${escapeHtml(stageLabel(step.stage, localizeUiText(step.label)))}</strong>
                  <small>${escapeHtml(localizeUiText(step.status_label))}</small>
                </div>
                ${index < steps.length - 1 ? '<div class="story-step-line"></div>' : ""}
              </div>
              `}
            `
          )
          .join("")}
      </div>
    </div>
  `;
}

function buildPrimaryAttemptSteps(steps = [], repairStory = {}) {
  const failedStage = String(repairStory.failed_stage || "").trim();
  const failedIndex = steps.findIndex((step) => String(step.stage || "") === failedStage);
  if (failedIndex === -1) {
    return steps;
  }
  return steps.map((step, index) => {
    if (index < failedIndex) {
      return {
        ...step,
        status: "completed",
        status_label: statusLabelForStep("completed"),
        emphasis: "default",
      };
    }
    if (index === failedIndex) {
      return {
        ...step,
        status: "failed",
        status_label: statusLabelForStep("failed", step.status_label),
        emphasis: "failed",
      };
    }
    return {
      ...step,
      status: "pending",
      status_label: statusLabelForStep("pending"),
      emphasis: "default",
    };
  });
}

function resolveRerunCurrentContext(story = {}, repairStory = {}, repair = {}) {
  const steps = Array.isArray(story.steps) ? story.steps : [];
  const rewindStage = String(repairStory.rewind_to || "").trim();
  const rewindIndex = steps.findIndex((step) => String(step.stage || "") === rewindStage);
  if (rewindIndex === -1) {
    return {
      stage: "",
      status: "pending",
      status_label: statusLabelForStep("pending"),
    };
  }

  const storyCurrentStage = String(story.current_stage?.stage || "").trim();
  const storyCurrentStatus = String(story.current_stage?.status || "").trim();
  const storyCurrentIndex = steps.findIndex((step) => String(step.stage || "") === storyCurrentStage);
  if (storyCurrentIndex >= rewindIndex && ["running", "starting"].includes(storyCurrentStatus)) {
    return {
      stage: storyCurrentStage,
      status: storyCurrentStatus,
      status_label: statusLabelForStep(storyCurrentStatus, story.current_stage?.status_label || ""),
    };
  }

  const liveStep = steps.find(
    (step, absoluteIndex) => absoluteIndex >= rewindIndex && ["running", "starting"].includes(String(step.status || "").trim())
  );
  if (liveStep) {
    return {
      stage: String(liveStep.stage || ""),
      status: String(liveStep.status || "running"),
      status_label: statusLabelForStep(String(liveStep.status || "running"), liveStep.status_label || ""),
    };
  }

  const rerunStep = Array.isArray(repairStory.steps)
    ? repairStory.steps.find((step) => String(step.kind || "") === "rerun") || {}
    : {};
  const rerunStatus = String(rerunStep.status || repair.status || "").trim();
  if (["running", "starting", "failed", "blocked"].includes(rerunStatus)) {
    const normalizedStatus = rerunStatus === "blocked" ? "failed" : rerunStatus;
    return {
      stage: rewindStage,
      status: normalizedStatus,
      status_label: statusLabelForStep(normalizedStatus),
    };
  }

  return {
    stage: "",
    status: "pending",
    status_label: statusLabelForStep("pending"),
  };
}

function buildRerunSteps(story = {}, repairStory = {}, repair = {}) {
  const steps = Array.isArray(story.steps) ? story.steps : [];
  const rewindStage = String(repairStory.rewind_to || "").trim();
  const rewindIndex = steps.findIndex((step) => String(step.stage || "") === rewindStage);
  if (rewindIndex === -1) {
    return [];
  }

  const rerunCurrent = resolveRerunCurrentContext(story, repairStory, repair);
  const currentStage = String(rerunCurrent.stage || "").trim();
  const currentIndex = steps.findIndex((step) => String(step.stage || "") === currentStage);

  return steps.map((step, absoluteIndex) => {
    if (absoluteIndex < rewindIndex) {
      return {
        placeholder: true,
        stage: String(step.stage || ""),
      };
    }

    let status = "pending";
    let statusLabel = statusLabelForStep("pending");
    let emphasis = "default";

    if (currentIndex !== -1 && absoluteIndex < currentIndex) {
      status = "completed";
      statusLabel = statusLabelForStep("completed");
      emphasis = absoluteIndex === rewindIndex ? "rewind" : "default";
    } else if (currentIndex !== -1 && absoluteIndex === currentIndex) {
      status = String(rerunCurrent.status || "running");
      statusLabel = statusLabelForStep(status, rerunCurrent.status_label || "");
      emphasis = status === "failed" ? "failed" : "current";
    } else if (absoluteIndex === rewindIndex) {
      emphasis = "rewind";
    }

    return {
      ...step,
      status,
      status_label: statusLabel,
      emphasis,
    };
  });
}

function renderRepairStoryStrip(story = {}, repairStory = {}, repair = {}) {
  const steps = Array.isArray(story.steps) ? story.steps : [];
  if (!steps.length) {
    return "";
  }
  const storyUi = story.ui || {};
  const rewindIndex = steps.findIndex((step) => String(step.stage || "") === String(repairStory.rewind_to || ""));
  const rewindLabel = rewindIndex >= 0
    ? stageLabel(steps[rewindIndex].stage, steps[rewindIndex].label || repairStory.rewind_to_label || repairStory.rewind_to || "되돌아감")
    : stageLabel(repairStory.rewind_to, repairStory.rewind_to_label || repairStory.rewind_to || "되돌아감");
  const currentAction = localizeUiText(repairStory.current_action || repairStory.summary || `${rewindLabel} 단계 재실행 진행 중입니다.`);
  const primarySteps = buildPrimaryAttemptSteps(steps, repairStory);
  const rerunSteps = buildRerunSteps(story, repairStory, repair);
  const connectorLabel = localizeUiText(storyUi.connector_label || `${rewindLabel} 단계로 되돌아감`);

  if (!rerunSteps.length) {
    return renderStoryLane("", "", storyUi.steps || steps, "story-strip-primary");
  }

  const primaryLaneSteps = storyUi.steps ? buildPrimaryAttemptSteps(storyUi.steps, repairStory) : primarySteps;
  const rerunLaneSteps = storyUi.steps ? buildRerunSteps({ ...story, steps: storyUi.steps }, repairStory, repair) : rerunSteps;
  const rerunEntryIndex = rerunLaneSteps.findIndex((step) => !step?.placeholder);
  if (rerunEntryIndex !== -1) {
    rerunLaneSteps[rerunEntryIndex] = {
      ...rerunLaneSteps[rerunEntryIndex],
      entry: true,
      entry_label: connectorLabel,
    };
  }

  return `
    <section class="run-story-block story-rewind-section">
      <div class="story-rewind-graph">
        ${renderStoryLane(storyUi.primary_lane_label || "처음 실행", "", primaryLaneSteps, "story-strip-primary")}
        ${renderStoryLane(storyUi.rerun_lane_label || `${rewindLabel}부터 다시 실행`, "", rerunLaneSteps, "story-strip-rerun")}
      </div>
    </section>
  `;
}

function renderStoryStrip(story = {}, repairStory = {}, repair = {}) {
  if (repairStory.active && repairStory.rewind_to) {
    return renderRepairStoryStrip(story, repairStory, repair);
  }
  const steps = Array.isArray(story.steps) ? story.steps : [];
  if (!steps.length) {
    return "";
  }
  const storyUi = story.ui || {};
  return `
    <section class="run-story-block">
      ${renderStoryLane("", "", storyUi.steps || steps, "story-strip-primary")}
    </section>
  `;
}

function renderCompactRetrievalSummary(retrieval = {}) {
  if (!retrieval.active) {
    return "";
  }
  const items = Array.isArray(retrieval.items) ? retrieval.items : [];
  const summary = items
    .map((item) => `${localizeUiText(item.label || item.corpus || "")} ${localizeUiText(item.status_label || item.status || "")}`.trim())
    .filter(Boolean)
    .join(" / ");
  return `
    <div class="repair-retrieval-strip">
      <span>인덱싱</span>
      <small>${escapeHtml(summary || localizeUiText(retrieval.summary) || "인덱싱 준비 상태를 확인하는 중입니다.")}</small>
    </div>
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
        <span class="section-kicker">${escapeHtml(localizeUiText(retrieval.headline || "인덱싱 준비"))}</span>
        <small>${escapeHtml(localizeUiText(retrieval.summary || ""))}</small>
      </div>
      <div class="retrieval-chip-list">
        ${items
          .map(
            (item) => `
              <div class="retrieval-chip ${escapeHtml(item.status || "queued")}">
                <strong>${escapeHtml(localizeUiText(item.label || item.corpus || ""))}</strong>
                <small>${escapeHtml(localizeUiText(item.status_label || ""))}</small>
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
  const repairUi = repairStory.ui || {};
  const focusTitle = options.focusTitle || "Focus";
  const focusHtml = options.focusHtml || '<div class="empty-state">표시할 세부 내용이 없습니다.</div>';
  const summaryCards = Array.isArray(repairUi.summary_cards) && repairUi.summary_cards.length
    ? repairUi.summary_cards
    : fallbackRepairSummaryCards(repairStory, repair);
  const statusLine = repairUi.status_line || repairStory.current_action || repair.current_action || repair.stop_reason_text || "재실행 단계를 준비 중입니다.";
  return `
    <section class="repair-summary-block">
      <div class="repair-summary-grid">
        ${summaryCards
          .map(
            (card) => `
              <div class="repair-fact ${escapeHtml(card.key === "diagnosis" ? "rewind" : card.key === "rewind" ? "current" : "fail")}">
                <span>${escapeHtml(localizeUiText(card.title || ""))}</span>
                <strong>${escapeHtml(localizeUiText(card.headline || "-"))}</strong>
                ${
                  [card.detail, card.timestamp].some(Boolean)
                    ? `<small>${
                        card.detail ? escapeHtml(localizeUiText(card.detail || "")) : ""
                      }${
                        card.detail && card.timestamp ? " · " : ""
                      }${
                        card.timestamp ? escapeHtml(formatTimestamp(card.timestamp)) : ""
                      }</small>`
                    : ""
                }
              </div>
            `
          )
          .join("")}
      </div>
      <div class="repair-status-strip">
        <span>현재 상태</span>
        <strong>${escapeHtml(localizeUiText(shortRepairStatusLabel(repair)))}</strong>
        <small>${escapeHtml(localizeUiText(statusLine))}</small>
      </div>
      <div class="repair-focus-shell">
        <div class="repair-focus-body">
          <div class="story-section-head">
            <span class="section-kicker">선택한 단계 상세</span>
            <small>${escapeHtml(localizeUiText(focusTitle))}</small>
          </div>
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
          <span>개발자 로그</span>
          <small>${events.length ? `최근 이벤트 ${events.length}개` : "최근 이벤트 없음"}</small>
        </summary>
        <div class="raw-log-body" data-raw-log-body>
          ${
            logPath
              ? `<div class="raw-log-meta"><strong>로그 파일</strong><small>${escapeHtml(logPath)}</small></div>`
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
                          <strong>${escapeHtml(stageLabel(event.stage, localizeUiText(event.stage || "-")))}</strong>
                          <div class="raw-log-copy">
                            <small class="raw-log-primary">${escapeHtml(localizeUiText(event.display_summary || event.summary || event.event_type || "-"))}</small>
                            ${
                              renderRawLogMeta(event)
                                ? `<small class="raw-log-secondary">${escapeHtml(renderRawLogMeta(event))}</small>`
                                : ""
                            }
                          </div>
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
  const rawBody = refs.stageDetail.querySelector("[data-raw-log-body]");
  if (rawPanel) {
    rawPanel.addEventListener("toggle", () => {
      state.rawLogOpen = rawPanel.open;
      persistRunUiState();
    });
  }
  if (rawBody) {
    rawBody.scrollTop = state.rawLogAutoFollow
      ? rawLogMaxScrollTop(rawBody)
      : Math.max(0, Number(state.rawLogScrollTop) || 0);
    rawBody.addEventListener("scroll", () => {
      state.rawLogScrollTop = Math.max(0, Number(rawBody.scrollTop) || 0);
      state.rawLogAutoFollow = rawLogNearBottom(rawBody);
      persistRunUiState();
    });
  }
}

function wrapStageDetail(title, html, kicker = "선택한 단계 상세") {
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
  if (stageKey === "indexing") return renderIndexing(details.indexing || {}, compact);
  if (stageKey === "validation") return renderValidation(details.validation || {}, payload.services || [], payload.demo || {}, compact);
  return "";
}

function renderImport(details = {}, compact = false) {
  const limits = viewLimits(compact);
  const summaryHtml = details.summary
    ? `<div class="fact-list"><div class="fact-list-item"><strong>요약</strong><small>${escapeHtml(localizeUiText(details.summary))}</small></div></div>`
    : "";
  return `
    ${renderCards(details.cards, limits)}
    ${summaryHtml}
  `;
}

function renderIndexing(details = {}, compact = false) {
  const limits = { ...viewLimits(compact), list: 2 };
  const summaryHtml = details.summary
    ? `<div class="fact-list"><div class="fact-list-item"><strong>요약</strong><small>${escapeHtml(localizeUiText(details.summary))}</small></div></div>`
    : "";
  return `
    ${renderCards(details.cards, limits)}
    ${renderList(details.corpora || [], (item) => `
      <div class="fact-list-item">
        <strong>${escapeHtml(item.label)}</strong>
        <small>${escapeHtml(item.value)}${item.caption ? ` / ${escapeHtml(item.caption)}` : ""}</small>
      </div>
    `, limits)}
    ${renderList(details.smoke_checks || [], (item) => `
      <div class="fact-list-item">
        <strong>${escapeHtml(item.label)}</strong>
        <small>${escapeHtml(item.value)}${item.caption ? ` / ${escapeHtml(item.caption)}` : ""}</small>
      </div>
    `, limits)}
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
      status_label: "대기",
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
    displayStages[diffIndex].status_label = statusLabelForStep("running");
  } else {
    displayStages[diffIndex].status_label = statusLabelForStep(target.status, target.status_label);
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
  const liveStage = resolveLiveStage(state.lastPayload, stages);
  refs.stageTimeline.innerHTML = stages
    .map((stage) => {
      const isActive = state.selectedStage === stage.stage;
      const isLive = liveStage === stage.stage;
      const copy = STAGE_COPY[stage.stage] || {};
      const flag = stageFlag(stage);
      const muted = repairStory.active && !flag && !isLive ? "stage-link-muted" : "";
      const anchor = flag ? `anchor-${escapeHtml(flag.className)}` : "";
      const liveChip = isLive && !flag ? '<span class="stage-mini-flag live">진행 중</span>' : "";
      return `
        <button type="button" class="stage-link ${isActive ? "active" : ""} ${isLive ? "stage-link-live" : ""} ${muted} ${anchor} ${flag ? `marker-${escapeHtml(flag.className)}` : ""}" data-stage="${escapeHtml(stage.stage)}">
          <div class="stage-link-head">
            <h3>${escapeHtml(stageLabel(stage.stage, localizeUiText(stage.label)))}</h3>
            <div class="stage-link-meta">
              ${liveChip}
              ${flag ? `<span class="stage-mini-flag ${escapeHtml(flag.className)}">${escapeHtml(flag.label)}</span>` : ""}
              <small>${escapeHtml(localizeUiText(stage.status_label))}</small>
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
  if (details.live?.active_phase) {
    return renderLiveStagePanel(details.live);
  }
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
  if (details.live?.active_phase) {
    return renderLiveStagePanel(details.live);
  }
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
        <strong>호스트</strong>
        <small>${escapeHtml(item)}</small>
      </div>
    `, limits)}
    ${renderList(details.chatbot_targets || [], (item) => `
        <div class="fact-list-item">
        <strong>챗봇</strong>
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
        <strong>적용 파일</strong>
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
        ? `<div class="fact-list"><div class="fact-list-item"><strong>재현 메모</strong><small>${escapeHtml(localizeUiText(details.failure_summary))}</small></div></div>`
        : ""
    }
  `;
}

function renderServiceGrid(services = [], demo = {}, limits = LIMITS) {
  const visibleServices = limitItems(services, limits.services);
  if (!visibleServices.length) {
    return `
      <div class="demo-banner ${statusClass(demo.status || "pending")}">
        <strong>${escapeHtml(localizeUiText(demo.status_label || "검증 대기"))}</strong>
        <small>${escapeHtml(localizeUiText(demo.message || "서비스는 검증 이후에 시작됩니다."))}</small>
      </div>
    `;
  }

  return `
    <div class="demo-banner ${statusClass(demo.status || "pending")}">
      <strong>${escapeHtml(localizeUiText(demo.status_label || "Bilyeo"))}</strong>
      <small>${escapeHtml(localizeUiText(demo.message || ""))}</small>
    </div>
    <div class="service-grid">
      ${visibleServices
        .map(
          (service) => `
            <div class="service-card">
              <div class="service-card-head">
                <strong>${escapeHtml(localizeUiText(service.label))}</strong>
                <span class="status-badge ${statusClass(service.status)}">${escapeHtml(localizeUiText(service.status_label))}</span>
              </div>
              <p>${escapeHtml(localizeUiText(service.reason || service.url || ""))}</p>
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

function renderDemoPrimaryAction(demo = {}) {
  const action = demo.primary_action || {};
  const url = String(action.url || demo.open_url || "").trim();
  if (!url) {
    return "";
  }
  const label = String(action.label || "사이트 열기").trim() || "사이트 열기";
  return `
    <div class="demo-primary-action">
      <a class="launch-button demo-primary-link" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">
        ${escapeHtml(localizeUiText(label))}
      </a>
    </div>
  `;
}

function renderValidationProgress(details = {}) {
  const progress = details.progress || {};
  const parts = [
    Number.isFinite(Number(progress.total)) && Number(progress.total) > 0 ? `전체 ${progress.total}` : "",
    Number(progress.passed) > 0 ? `통과 ${progress.passed}` : "",
    Number(progress.running) > 0 ? `진행 ${progress.running}` : "",
    Number(progress.pending) > 0 ? `대기 ${progress.pending}` : "",
    Number(progress.failed) > 0 ? `실패 ${progress.failed}` : "",
    Number(progress.skipped) > 0 ? `건너뜀 ${progress.skipped}` : "",
  ].filter(Boolean);
  if (!parts.length) {
    return "";
  }
  return `
    <div class="validation-summary-line">
      <strong>검증 진행 현황</strong>
      <small>${escapeHtml(parts.join(" · "))}</small>
    </div>
  `;
}

function renderValidationChecks(details = {}, compact = false) {
  const checks = Array.isArray(details.checks) ? details.checks.filter((item) => item != null) : [];
  if (!checks.length) {
    return '<div class="empty-state">검증 체크 결과가 아직 없습니다.</div>';
  }
  return `
    <div class="validation-check-stream">
      ${checks
        .map(
          (item) => `
            <div class="validation-check-row">
              <span class="status-badge ${statusClass(item.status || "pending")}">${escapeHtml(localizeUiText(item.status_label || "대기"))}</span>
              <div class="validation-check-copy">
                <strong>${escapeHtml(localizeUiText(item.label || item.name || "-"))}</strong>
                <small>${escapeHtml(localizeUiText(item.summary || ""))}</small>
              </div>
            </div>
          `
        )
        .join("")}
    </div>
  `;
}

function renderValidationWarnings(details = {}, demo = {}) {
  const warningText = String(
    details.validation_warning_summary || demo.validation_warning_summary || ""
  ).trim();
  const missingCorpora = Array.isArray(demo.missing_retrieval_corpora)
    ? demo.missing_retrieval_corpora.filter(Boolean)
    : [];
  const demoAuth = demo.demo_auth || details.demo_auth || {};
  const notes = [];
  if (warningText) notes.push(warningText);
  if (missingCorpora.length) notes.push(`누락 코퍼스: ${missingCorpora.join(", ")}`);
  if (!notes.length && !demoAuth.email) {
    return "";
  }
  return `
    <div class="fact-list">
      ${notes
        .map(
          (note) => `
            <div class="fact-list-item">
              <strong>주의</strong>
              <small>${escapeHtml(localizeUiText(note))}</small>
            </div>
          `
        )
        .join("")}
      ${
        demoAuth.email
          ? `
            <div class="fact-list-item">
              <strong>데모 로그인</strong>
              <small>${escapeHtml(demoAuth.email)}</small>
            </div>
          `
          : ""
      }
    </div>
  `;
}

function renderValidation(details = {}, services = [], demo = {}, compact = false) {
  const limits = viewLimits(compact);
  const proofLink = demo.preview_url
    ? `<div class="fact-list"><div class="fact-list-item"><strong>미리보기</strong><small>${escapeHtml(demo.preview_url)}</small></div></div>`
    : "";

  return `
    ${renderServiceGrid(services, demo, limits)}
    ${renderDemoPrimaryAction(demo)}
    ${renderValidationWarnings(details, demo)}
    ${renderValidationProgress(details)}
    ${renderValidationChecks(details, compact)}
    ${renderHighlights(details.proofs || [], limits)}
    ${proofLink}
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
        ? `<div class="fact-list"><div class="fact-list-item"><strong>원인 설명</strong><small>${escapeHtml(localizeUiText(repair.diagnosis_summary))}</small></div></div>`
        : ""
    }
    ${
      repair.stop_reason_text
        ? `<div class="fact-list"><div class="fact-list-item"><strong>중단 이유</strong><small>${escapeHtml(localizeUiText(repair.stop_reason_text))}</small></div></div>`
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
        <strong>오류</strong>
        ${error.source ? `<span class="status-badge fail">${escapeHtml(error.source)}</span>` : ""}
      </div>
      <p>${escapeHtml(localizeUiText(error.message || "알 수 없는 오류가 발생했습니다."))}</p>
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
  return ["ready", "failed", "blocked", "disabled"].includes(status);
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
  const existingRawBody = refs.stageDetail.querySelector("[data-raw-log-body]");
  if (existingRawBody) {
    state.rawLogAutoFollow = rawLogNearBottom(existingRawBody);
    state.rawLogScrollTop = Math.max(0, Number(existingRawBody.scrollTop) || 0);
  }
  renderRunStoryPanel(payload);
  const selected = state.selectedStage;
  const details = payload.details || {};
  const stages = (state.displayStages && state.displayStages.length ? state.displayStages : payload.stages) || [];
  const stageView = stages.find((item) => item.stage === selected) || null;
  const story = payload.story || {};
  const repairStory = payload.repair_story || {};
  const repair = payload.repair || {};
  const storyUi = story.ui || {};
  const focusStage = story.focus_stage || story.current_stage || {};
  const failedLabel = repairStory.failed_stage_label || repair.failed_stage_label || repairStory.failed_stage || "";
  const rewindLabel = repairStory.rewind_to_label || repair.effective_rewind_label || repairStory.rewind_to || "";
  const detailStageKey = repairStory.active ? String(focusStage.stage || selected || "analysis") : selected;
  const stageDetails = details[detailStageKey] || {};
  const liveDetail = !repairStory.active ? (stageDetails.live || {}) : {};
  const copy = STAGE_COPY[detailStageKey] || STAGE_COPY.analysis;
  const panelStatus = repairStory.active
    ? {
        label: shortRepairStatusLabel(repair),
        status: repair.status || payload.run.status,
      }
    : {
        label: story.current_stage?.status_label || payload.run.status_label || (stageView ? stageView.status_label : "대기"),
        status: story.current_stage?.status || payload.run.status || (stageView ? stageView.status : "pending"),
      };

  refs.detailTitle.textContent = repairStory.active
    ? stageLabel(detailStageKey, localizeUiText(focusStage.label || stageView?.label || copy.title))
    : stageLabel(detailStageKey, localizeUiText(focusStage.label || stageView?.label || copy.title));
  refs.detailDescription.textContent = repairStory.active
    ? `${stageLabel(detailStageKey, localizeUiText(focusStage.label || copy.title))} 단계를 다시 기준으로 확인 중입니다.`
    : localizeUiText(describeLivePhase(liveDetail) || story.summary || storyUi.headline || story.headline || copy.description);
  refs.detailStatus.textContent = localizeUiText(panelStatus.label || "대기");
  refs.detailStatus.className = `status-badge ${statusClass(panelStatus.status || "pending")}`;

  const html = renderStageDetailContent(detailStageKey, details, payload, repairStory.active ? "repair" : true);

  const stageDetailSection = wrapStageDetail(
    stageLabel(detailStageKey, localizeUiText(focusStage.label || copy.title)),
    html || '<div class="empty-state">이 단계에서 표시할 내용이 아직 없습니다.</div>',
    "선택한 단계 상세"
  );

  refs.stageDetail.classList.remove("with-sidepane");
  refs.stageDetail.innerHTML = repairStory.active
    ? `
      <div class="story-panel repair-mode">
        ${renderRepairStory(repairStory, repair, {
          focusTitle: stageLabel(detailStageKey, localizeUiText(focusStage.label || copy.title)),
          focusHtml: html || '<div class="empty-state">이 단계에서 표시할 내용이 아직 없습니다.</div>',
        })}
        ${state.lastError ? renderErrorPane(state.lastError) : ""}
        ${renderRawEventLog(payload)}
      </div>
    `
    : `
      <div class="story-panel">
        ${state.lastError ? renderErrorPane(state.lastError) : ""}
        ${stageDetailSection}
        ${renderRawEventLog(payload)}
      </div>
    `;
  bindStoryInteractions();
  persistRunUiState();
}

function currentProjectOption() {
  const site = formValue("site");
  return (state.config?.project_options || []).find((item) => item.site === site) || null;
}

async function loadConfig() {
  state.config = await request("/api/config");
  const options = state.config.project_options || [];
  if (refs.siteSelect) {
    refs.siteSelect.innerHTML = options
      .map((item) => `<option value="${escapeHtml(item.site)}">${escapeHtml(item.site)}</option>`)
      .join("");
  }

  if (options[0] && refs.siteSelect) {
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
  const body = new FormData();
  body.append("repo_url", formValue("repo-url"));
  const envTargetPath = formValue("github-env-target");
  if (envTargetPath) {
    body.append("env_target_path", envTargetPath);
  }
  const envFile = refs.githubEnvFileInput?.files?.[0];
  if (envFile) {
    body.append("env_file", envFile);
  }
  return body;
}

function resetActionButtons() {
  if (refs.launchButton) {
    refs.launchButton.disabled = false;
    refs.launchButton.textContent = "프리셋 실행";
  }
  if (refs.githubLaunchButton) {
    refs.githubLaunchButton.disabled = false;
    refs.githubLaunchButton.textContent = "가져오기";
  }
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
  state.rawLogScrollTop = 0;
  state.rawLogAutoFollow = true;
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

function renderRunStoryPanel(payload) {
  if (!refs.runStoryShell) {
    return;
  }
  if (!payload) {
    refs.runStoryShell.className = "run-story-shell empty-state";
    refs.runStoryShell.innerHTML = `
      <div class="story-flow-head">
        <span class="section-kicker">진행 흐름</span>
      </div>
      <div class="empty-state">온보딩을 시작하면 전체 진행 흐름 그래프가 이 영역에 고정 표시됩니다.</div>
    `;
    return;
  }
  const content = renderStoryStrip(payload.story || {}, payload.repair_story || {}, payload.repair || {});
  refs.runStoryShell.className = "run-story-shell";
  refs.runStoryShell.innerHTML = `
    <div class="story-flow-head">
      <span class="section-kicker">진행 흐름</span>
    </div>
    ${content || '<div class="empty-state">표시할 진행 흐름이 아직 없습니다.</div>'}
  `;
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
  renderRunStoryPanel(payload);
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
  if (!state.lastPayload) {
    renderRunStoryPanel(null);
  }
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

if (refs.form) {
refs.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (refs.launchButton) {
    refs.launchButton.disabled = true;
    refs.launchButton.textContent = "실행 중";
  }
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
}

if (refs.githubForm) {
refs.githubForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (refs.githubLaunchButton) {
    refs.githubLaunchButton.disabled = true;
    refs.githubLaunchButton.textContent = "가져오는 중";
  }
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
      body: serializeGithubImportForm(),
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
}

function renderInitialStageMenu() {
  state.displayStages = ["import", "analysis", "planning", "compile", "apply", "export", "indexing", "validation"].map((stage) => ({
      stage,
      label: STAGE_COPY[stage].title,
      status: "pending",
      status_label: "대기",
    }));
  renderStageMenu(state.displayStages);
}

async function boot() {
  renderInitialStageMenu();
  renderRunStoryPanel(null);
  try {
    await loadConfig();
    restoreRunFromQuery();
  } catch (error) {
    showError(error);
  }
}

boot();
