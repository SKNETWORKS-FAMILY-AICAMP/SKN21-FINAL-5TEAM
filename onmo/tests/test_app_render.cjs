const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function createElement(id = "") {
  const listeners = {};
  const nodes = {};
  let html = "";
  let version = 0;

  function ensureNode(key, factory) {
    const existing = nodes[key];
    if (existing && existing.version === version) {
      return existing.node;
    }
    const node = factory();
    nodes[key] = { version, node };
    return node;
  }

  function ensurePanel(key, openPattern) {
    return ensureNode(key, () => ({
      open: openPattern.test(html),
      listeners: {},
      addEventListener(type, handler) {
        this.listeners[type] = handler;
      },
    }));
  }

  function ensureScrollContainer(key) {
    return ensureNode(key, () => ({
      scrollTop: 0,
      get clientHeight() {
        return 180;
      },
      get scrollHeight() {
        const rowCount = (html.match(/raw-log-row/g) || []).length;
        return Math.max(240, rowCount * 28 + 120);
      },
      listeners: {},
      addEventListener(type, handler) {
        this.listeners[type] = handler;
      },
    }));
  }

  return {
    id,
    value: "",
    textContent: "",
    get innerHTML() {
      return html;
    },
    set innerHTML(value) {
      html = String(value || "");
      version += 1;
    },
    className: "",
    disabled: false,
    open: false,
    dataset: {},
    listeners,
    addEventListener(type, handler) {
      listeners[type] = handler;
    },
    querySelector(selector) {
      if (selector === "[data-raw-log-panel]" && html.includes("data-raw-log-panel")) {
        return ensurePanel("raw", /data-raw-log-panel[^>]*\sopen(?=[\s>])/);
      }
      if (selector === "[data-story-snapshot-panel]" && html.includes("data-story-snapshot-panel")) {
        return ensurePanel("story", /data-story-snapshot-panel[^>]*\sopen(?=[\s>])/);
      }
      if (selector === "[data-raw-log-body]" && html.includes("data-raw-log-body")) {
        return ensureScrollContainer("raw-log-body");
      }
      return null;
    },
    querySelectorAll() {
      return [];
    },
    classList: {
      add() {},
      remove() {},
      contains() {
        return false;
      },
    },
  };
}

function createStorage(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    getItem(key) {
      return store.has(key) ? store.get(key) : null;
    },
    setItem(key, value) {
      store.set(key, String(value));
    },
    removeItem(key) {
      store.delete(key);
    },
    clear() {
      store.clear();
    },
  };
}

function dashboardPayload() {
  return {
    run: { site: "bilyeo", run_id: "bilyeo-v2-repair-009", status: "running", status_label: "Running" },
    process: { running: true, log_path: "/tmp/onmo.log" },
    demo: { status: "disabled", status_label: "GitHub Mode" },
    story: {
      headline: "현재 Analysis 단계가 진행 중입니다.",
      summary: "기존 이벤트를 불러오는 중입니다.",
      current_stage: { stage: "analysis", label: "Analysis", status: "running", status_label: "Running" },
      focus_stage: { stage: "analysis", label: "Analysis", status: "running", status_label: "Running" },
      steps: [
        { stage: "import", label: "Import", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "analysis", label: "Analysis", status: "running", status_label: "Running", emphasis: "current" },
      ],
      retrieval: { active: false, headline: "", summary: "", items: [] },
    },
    repair_story: { active: false, headline: "", summary: "", steps: [], failed_stage: "", rewind_to: "" },
    repair: { active: false },
    details: { analysis: { cards: [], highlights: [] } },
    recent_events: [{ timestamp: "2026-03-27T10:10:00+09:00", stage: "analysis", summary: "analysis rerun started" }],
    stages: [
      { stage: "import", label: "Import", status: "completed", status_label: "Completed" },
      { stage: "analysis", label: "Analysis", status: "running", status_label: "Running" },
    ],
  };
}

function loadApp(options = {}) {
  const elements = new Map();
  const ids = [
    "start-form",
    "github-form",
    "hero-status-text",
    "launch-button",
    "github-launch-button",
    "run-meta",
    "stage-timeline",
    "detail-title",
    "detail-status",
    "detail-description",
    "run-story-shell",
    "stage-detail",
    "site",
    "repo-url",
    "github-env-file",
    "github-env-target",
  ];
  ids.forEach((id) => elements.set(id, createElement(id)));
  const sessionStorage = createStorage(options.sessionStorage || {});
  const location = {
    search: options.search || "",
    pathname: "/",
    hash: "",
    assign() {},
  };
  const historyCalls = [];

  const context = {
    console,
    URLSearchParams,
    FormData: class FormData {
      constructor() {
        this.entries = [];
      }

      append(key, value) {
        this.entries.push([key, value]);
      }
    },
    setTimeout() {
      return 1;
    },
    clearTimeout() {},
    setInterval() {
      return 1;
    },
    clearInterval() {},
    fetch: async (url) => ({
      ok: true,
      async json() {
        if (String(url).includes("/api/config")) {
          return {
            project_options: [{ site: "bilyeo", source_root: "bilyeo", generated_root: "generated-v2", runtime_root: "runtime-v2" }],
            generated_root_default: "generated-v2",
            runtime_root_default: "runtime-v2",
            preview_url_default: "http://127.0.0.1:3000",
          };
        }
        return options.dashboardPayload || dashboardPayload();
      },
    }),
    document: {
      getElementById(id) {
        return elements.get(id) || createElement(id);
      },
    },
    sessionStorage,
    window: {
      setTimeout() {
        return 1;
      },
      clearTimeout() {},
      setInterval() {
        return 1;
      },
      clearInterval() {},
      location,
      sessionStorage,
      history: {
        replaceState(_state, _title, url = "") {
          historyCalls.push(url);
          if (!url) {
            location.search = "";
            return;
          }
          const parsed = new URL(url, "http://localhost");
          location.pathname = parsed.pathname;
          location.search = parsed.search;
          location.hash = parsed.hash;
        },
      },
    },
  };
  context.globalThis = context;

  const scriptPath = path.resolve(__dirname, "../static/app.js");
  const source = `${fs.readFileSync(scriptPath, "utf8")}\n;globalThis.__test_api__ = { renderSelectedStage, renderStageMenu, pickDefaultStage, stepStagePlayback, restoreRunFromQuery, beginRunTracking, refs, state };`;
  vm.runInNewContext(source, context, { filename: scriptPath });
  return { ...context.__test_api__, sessionStorage, window: context.window, historyCalls };
}

function repairPayload() {
  return {
    run: {
      site: "bilyeo",
      run_id: "bilyeo-v2-repair-009",
      status: "failed",
      status_label: "Failed",
    },
    process: { running: false, log_path: "/tmp/onmo.log" },
    demo: { status: "blocked", status_label: "Bilyeo blocked" },
    services: [],
    story: {
      headline: "Planning 단계에서 실행이 중단되었습니다.",
      summary: "분석 단계부터 다시 실행하도록 결정했습니다.",
      current_stage: { stage: "planning", label: "Planning", status: "failed", status_label: "Failed" },
      focus_stage: { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed" },
      steps: [
        { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed", emphasis: "rewind" },
        { stage: "planning", label: "Planning", status: "failed", status_label: "Failed", emphasis: "failed" },
        { stage: "compile", label: "Compile", status: "pending", status_label: "Waiting", emphasis: "default" },
      ],
      retrieval: {
        active: true,
        headline: "Retrieval Ready",
        summary: "FAQ ready, Policy indexing",
        items: [
          { label: "FAQ", status: "ready", status_label: "Ready" },
          { label: "Policy", status: "indexing", status_label: "Indexing" },
        ],
      },
    },
    repair_story: {
      active: true,
      headline: "Repair Rewind",
      summary: "계획 단계에서 analysis coverage incomplete 문제가 발생해 분석 단계로 되감아 다시 확인하고 있습니다.",
      status_label: "분석 단계로 되감기",
      failed_stage: "planning",
      failed_stage_label: "계획",
      rewind_to: "analysis",
      rewind_to_label: "분석",
      problem: "계획 단계에서 analysis coverage incomplete 문제가 발생했습니다.",
      diagnosis: "분석 스냅샷이 계획에 필요한 auth_bootstrap, order_lookup, order_action 범위를 충분히 담지 못했습니다.",
      current_action: "분석 단계부터 다시 실행하도록 결정했습니다.",
      steps: [
        { kind: "failure", label: "계획 실패 감지", status: "completed", timestamp: "2026-03-25T15:32:14+09:00" },
        { kind: "diagnosis", label: "원인 진단 완료", status: "completed", timestamp: "2026-03-25T15:32:39+09:00" },
        { kind: "rewind", label: "분석로 되감기 결정", status: "completed", timestamp: "2026-03-25T15:32:39+09:00" },
        { kind: "rerun", label: "분석 재실행 시작", status: "running", timestamp: "2026-03-25T15:32:39+09:00" },
      ],
    },
    repair: {
      active: true,
      status: "running",
      status_label: "분석 단계로 되감기",
      failed_stage_label: "계획",
      effective_rewind_label: "분석",
      current_action: "분석 단계부터 다시 실행하도록 결정했습니다.",
    },
    details: {
      analysis: {
        cards: [{ label: "Analysis focus card", value: "selected analysis detail" }],
        highlights: [{ label: "Focus", value: "analysis rerun" }],
      },
      validation: {
        cards: [{ label: "Validation card", value: "blocked validation detail" }],
      },
    },
    recent_events: [],
    stages: [
      { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed" },
      { stage: "planning", label: "Planning", status: "failed", status_label: "Failed" },
      { stage: "compile", label: "Compile", status: "pending", status_label: "Waiting" },
    ],
  };
}

function repairRerunGraphPayload() {
  return {
    run: {
      site: "bilyeo",
      run_id: "bilyeo-v2-repair-graph-010",
      status: "running",
      status_label: "Running",
    },
    process: { running: true, log_path: "/tmp/onmo.log" },
    demo: { status: "disabled", status_label: "GitHub Mode" },
    services: [],
    story: {
      headline: "현재 Analysis 단계가 다시 진행 중입니다.",
      summary: "Validation 실패 이후 Analysis 단계부터 다시 실행 중입니다.",
      current_stage: { stage: "analysis", label: "Analysis", status: "running", status_label: "Running" },
      focus_stage: { stage: "analysis", label: "Analysis", status: "running", status_label: "Running" },
      steps: [
        { stage: "analysis", label: "Analysis", status: "running", status_label: "Running", emphasis: "current" },
        { stage: "planning", label: "Planning", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "compile", label: "Compile", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "apply", label: "Apply", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "export", label: "Export", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "indexing", label: "Indexing", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "validation", label: "Validation", status: "failed", status_label: "Failed", emphasis: "failed" },
      ],
      retrieval: { active: false, headline: "", summary: "", items: [] },
    },
    repair_story: {
      active: true,
      headline: "Repair Rewind",
      summary: "Validation 단계에서 실패해 Analysis부터 다시 진행 중입니다.",
      status_label: "분석 단계로 되감기",
      failed_stage: "validation",
      failed_stage_label: "검증",
      rewind_to: "analysis",
      rewind_to_label: "분석",
      problem: "Validation 단계에서 문제를 감지했습니다.",
      diagnosis: "이전 산출물을 다시 검증하기 위해 analysis부터 재실행합니다.",
      current_action: "Analysis 단계 재실행 진행 중입니다.",
      steps: [
        { kind: "failure", label: "검증 실패 감지", status: "completed", timestamp: "2026-03-27T19:40:04+09:00" },
        { kind: "diagnosis", label: "원인 진단 완료", status: "completed", timestamp: "2026-03-27T19:40:18+09:00" },
        { kind: "rewind", label: "분석으로 되감기 결정", status: "completed", timestamp: "2026-03-27T19:40:23+09:00" },
        { kind: "rerun", label: "분석 재실행 시작", status: "running", timestamp: "2026-03-27T19:40:24+09:00" },
      ],
    },
    repair: {
      active: true,
      status: "running",
      status_label: "분석 단계로 되감기",
      failed_stage_label: "검증",
      effective_rewind_label: "분석",
      current_action: "Analysis 단계 재실행 진행 중입니다.",
    },
    details: {
      analysis: {
        cards: [{ label: "Current", value: "rerun active" }],
      },
    },
    recent_events: [],
    stages: [
      { stage: "analysis", label: "Analysis", status: "running", status_label: "Running" },
      { stage: "planning", label: "Planning", status: "completed", status_label: "Completed" },
      { stage: "compile", label: "Compile", status: "completed", status_label: "Completed" },
      { stage: "apply", label: "Apply", status: "completed", status_label: "Completed" },
      { stage: "export", label: "Export", status: "completed", status_label: "Completed" },
      { stage: "indexing", label: "Indexing", status: "completed", status_label: "Completed" },
      { stage: "validation", label: "Validation", status: "failed", status_label: "Failed" },
    ],
  };
}

function compileRewindGraphPayload() {
  return {
    run: {
      site: "food",
      run_id: "food-v2-repair-graph-011",
      status: "running",
      status_label: "Running",
    },
    process: { running: true, log_path: "/tmp/onmo.log" },
    demo: { status: "disabled", status_label: "GitHub Mode" },
    services: [],
    story: {
      headline: "현재 Compile 단계가 다시 진행 중입니다.",
      summary: "Validation 실패 이후 Compile 단계부터 다시 실행 중입니다.",
      current_stage: { stage: "compile", label: "Compile", status: "running", status_label: "Running" },
      focus_stage: { stage: "compile", label: "Compile", status: "running", status_label: "Running" },
      steps: [
        { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "planning", label: "Planning", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "compile", label: "Compile", status: "running", status_label: "Running", emphasis: "current" },
        { stage: "apply", label: "Apply", status: "pending", status_label: "Waiting", emphasis: "default" },
        { stage: "export", label: "Export", status: "pending", status_label: "Waiting", emphasis: "default" },
        { stage: "indexing", label: "Indexing", status: "pending", status_label: "Waiting", emphasis: "default" },
        { stage: "validation", label: "Validation", status: "failed", status_label: "Failed", emphasis: "failed" },
      ],
      retrieval: { active: false, headline: "", summary: "", items: [] },
    },
    repair_story: {
      active: true,
      headline: "Repair Rewind",
      summary: "Validation 단계에서 실패해 Compile부터 다시 진행 중입니다.",
      status_label: "생성 단계로 되감기",
      failed_stage: "validation",
      failed_stage_label: "검증",
      rewind_to: "compile",
      rewind_to_label: "생성",
      problem: "Validation 단계에서 문제를 감지했습니다.",
      diagnosis: "생성 산출물부터 다시 점검해야 합니다.",
      current_action: "생성 단계 재실행 진행 중입니다.",
      steps: [
        { kind: "failure", label: "검증 실패 감지", status: "completed", timestamp: "2026-03-27T20:33:01+09:00" },
        { kind: "diagnosis", label: "원인 진단 완료", status: "completed", timestamp: "2026-03-27T20:33:12+09:00" },
        { kind: "rewind", label: "생성으로 되감기 결정", status: "completed", timestamp: "2026-03-27T20:33:18+09:00" },
        { kind: "rerun", label: "생성 재실행 시작", status: "running", timestamp: "2026-03-27T20:33:19+09:00" },
      ],
    },
    repair: {
      active: true,
      status: "running",
      status_label: "생성 단계로 되감기",
      failed_stage_label: "검증",
      effective_rewind_label: "생성",
      current_action: "생성 단계 재실행 진행 중입니다.",
    },
    details: {
      compile: {
        cards: [{ label: "Current", value: "compile rerun active" }],
      },
    },
    recent_events: [],
    stages: [
      { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed" },
      { stage: "planning", label: "Planning", status: "completed", status_label: "Completed" },
      { stage: "compile", label: "Compile", status: "running", status_label: "Running" },
      { stage: "apply", label: "Apply", status: "pending", status_label: "Waiting" },
      { stage: "export", label: "Export", status: "pending", status_label: "Waiting" },
      { stage: "indexing", label: "Indexing", status: "pending", status_label: "Waiting" },
      { stage: "validation", label: "Validation", status: "failed", status_label: "Failed" },
    ],
  };
}

function repairLiveRerunPayload() {
  return {
    run: {
      site: "food",
      run_id: "food-v2-repair-live-012",
      status: "running",
      status_label: "Running",
    },
    process: { running: true, log_path: "/tmp/onmo.log" },
    demo: { status: "disabled", status_label: "GitHub Mode" },
    services: [],
    story: {
      headline: "현재 검증 단계에서 실패가 감지되었습니다.",
      summary: "계획 단계부터 다시 실행 중입니다.",
      current_stage: { stage: "validation", label: "Validation", status: "failed", status_label: "Failed" },
      focus_stage: { stage: "planning", label: "Planning", status: "running", status_label: "Running" },
      steps: [
        { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "planning", label: "Planning", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "compile", label: "Compile", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "apply", label: "Apply", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "export", label: "Export", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "indexing", label: "Indexing", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "validation", label: "Validation", status: "failed", status_label: "Failed", emphasis: "failed" },
      ],
      retrieval: { active: false, headline: "", summary: "", items: [] },
    },
    repair_story: {
      active: true,
      headline: "Repair Rewind",
      summary: "검증 실패 이후 계획 단계부터 다시 실행 중입니다.",
      status_label: "계획 단계로 되감기",
      failed_stage: "validation",
      failed_stage_label: "검증",
      rewind_to: "planning",
      rewind_to_label: "계획",
      problem: "검증 단계에서 문제가 발생했습니다.",
      diagnosis: "계획 단계부터 다시 확인해야 합니다.",
      current_action: "계획 단계 재실행 진행 중입니다.",
      steps: [
        { kind: "failure", label: "검증 실패 감지", status: "completed", timestamp: "2026-03-30T11:20:01+09:00" },
        { kind: "diagnosis", label: "원인 진단 완료", status: "completed", timestamp: "2026-03-30T11:20:04+09:00" },
        { kind: "rewind", label: "계획으로 되감기 결정", status: "completed", timestamp: "2026-03-30T11:20:08+09:00" },
        { kind: "rerun", label: "계획 재실행 시작", status: "running", timestamp: "2026-03-30T11:20:10+09:00" },
      ],
    },
    repair: {
      active: true,
      status: "running",
      status_label: "계획 단계로 되감기",
      failed_stage_label: "검증",
      effective_rewind_label: "계획",
      current_action: "계획 단계 재실행 진행 중입니다.",
    },
    details: {
      planning: {
        cards: [{ label: "Current", value: "planning rerun active" }],
      },
    },
    recent_events: [],
    stages: [
      { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed" },
      { stage: "planning", label: "Planning", status: "completed", status_label: "Completed" },
      { stage: "compile", label: "Compile", status: "completed", status_label: "Completed" },
      { stage: "apply", label: "Apply", status: "completed", status_label: "Completed" },
      { stage: "export", label: "Export", status: "completed", status_label: "Completed" },
      { stage: "indexing", label: "Indexing", status: "completed", status_label: "Completed" },
      { stage: "validation", label: "Validation", status: "failed", status_label: "Failed" },
    ],
  };
}

test("repair mode renders a dedicated hero and uses focus stage details", async () => {
  const api = loadApp();
  const payload = repairPayload();
  api.state.selectedStage = "validation";
  api.state.lastPayload = payload;

  api.renderSelectedStage(payload);

  assert.equal(api.refs.detailTitle.textContent, "분석");
  assert.match(api.refs.stageDetail.innerHTML, /repair-summary-grid/);
  assert.match(api.refs.stageDetail.innerHTML, /문제 발생/);
  assert.match(api.refs.stageDetail.innerHTML, /오류 상세/);
  assert.match(api.refs.stageDetail.innerHTML, /진단 판단/);
  assert.match(api.refs.stageDetail.innerHTML, /되돌아감/);
  assert.match(api.refs.stageDetail.innerHTML, /현재 상태/);
  assert.match(api.refs.stageDetail.innerHTML, /Analysis focus card/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Validation card/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Why It Failed/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Re-enter Here/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Now Running/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /진행 흐름/);
});

test("repair mode keeps rewind target selected during playback and rail labels the anchors", async () => {
  const api = loadApp();
  const payload = repairPayload();
  api.state.lastPayload = payload;
  api.state.selectionPinned = false;
  api.state.selectedStage = "import";
  api.state.displayStages = [
    { stage: "analysis", label: "Analysis", status: "pending", status_label: "Waiting" },
    { stage: "planning", label: "Planning", status: "pending", status_label: "Waiting" },
    { stage: "compile", label: "Compile", status: "pending", status_label: "Waiting" },
  ];
  api.state.targetStages = payload.stages;

  api.stepStagePlayback();
  api.renderStageMenu(payload.stages);

  assert.equal(api.state.selectedStage, "analysis");
  assert.match(api.refs.stageTimeline.innerHTML, /오류 지점/);
  assert.match(api.refs.stageTimeline.innerHTML, /되돌아감/);
  assert.match(api.refs.stageTimeline.innerHTML, /stage-link-muted/);
});

test("restoreRunFromQuery falls back to persisted active run and restores panel state", async () => {
  const api = loadApp({
    sessionStorage: {
      "onmo.active-run": JSON.stringify({
        site: "bilyeo",
        run_id: "bilyeo-v2-repair-009",
        generated_root: "generated-v2",
      }),
      "onmo.run-ui:bilyeo:bilyeo-v2-repair-009": JSON.stringify({
        selectedStage: "planning",
        selectionPinned: true,
        rawLogOpen: true,
      }),
    },
  });

  const restored = api.restoreRunFromQuery();

  assert.equal(restored, true);
  assert.equal(
    JSON.stringify(api.state.currentRun),
    JSON.stringify({
      site: "bilyeo",
      run_id: "bilyeo-v2-repair-009",
      generated_root: "generated-v2",
    })
  );
  assert.equal(api.state.selectedStage, "planning");
  assert.equal(api.state.selectionPinned, true);
  assert.equal(api.state.rawLogOpen, true);
});

test("beginRunTracking persists the active run in the URL and session storage", async () => {
  const api = loadApp();

  api.beginRunTracking(
    {
      site: "food",
      run_id: "food-run-001",
      generated_root: "generated-v2",
    },
    "import"
  );

  assert.equal(
    api.sessionStorage.getItem("onmo.active-run"),
    JSON.stringify({
      site: "food",
      run_id: "food-run-001",
      generated_root: "generated-v2",
    })
  );
  assert.match(api.window.location.search, /site=food/);
  assert.match(api.window.location.search, /run_id=food-run-001/);
  assert.match(api.window.location.search, /generated_root=generated-v2/);
});

test("site panel row is not locked to a clipping fixed height", async () => {
  const stylesPath = path.resolve(__dirname, "../static/styles.css");
  const styles = fs.readFileSync(stylesPath, "utf8");

  assert.doesNotMatch(styles, /\.main-panel\s*\{[^}]*grid-template-rows:\s*104px minmax\(0,\s*1fr\)/s);
  assert.match(styles, /\.main-panel\s*\{[^}]*grid-template-rows:\s*minmax\(\d+px,\s*auto\)\s+auto\s+minmax\(0,\s*1fr\)/s);
});

test("indexing renders as a formal stage detail instead of only retrieval chips", async () => {
  const api = loadApp();
  const payload = {
    run: { site: "food", run_id: "food-demo-004", status: "running", status_label: "Running" },
    process: { running: true, log_path: "/tmp/onmo.log" },
    demo: { status: "disabled", status_label: "GitHub Mode" },
    story: {
      headline: "현재 Indexing 단계가 진행 중입니다.",
      summary: "retrieval corpus를 준비하는 중입니다.",
      current_stage: { stage: "indexing", label: "Indexing", status: "running", status_label: "Running" },
      focus_stage: { stage: "indexing", label: "Indexing", status: "running", status_label: "Running" },
      steps: [
        { stage: "export", label: "Export", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "indexing", label: "Indexing", status: "running", status_label: "Running", emphasis: "current" },
        { stage: "validation", label: "Validation", status: "pending", status_label: "Waiting", emphasis: "default" },
      ],
      retrieval: {
        active: true,
        headline: "Retrieval Ready",
        summary: "2개 corpus 중 1개 준비됨.",
        items: [
          { label: "FAQ", status: "ready", status_label: "Ready" },
          { label: "Policy", status: "indexing", status_label: "Indexing" },
        ],
      },
    },
    repair_story: { active: false, headline: "", summary: "", steps: [], failed_stage: "", rewind_to: "" },
    repair: { active: false },
    details: {
      indexing: {
        cards: [
          { label: "Corpora", value: "2" },
          { label: "Ready", value: "1" },
        ],
        corpora: [
          { label: "FAQ", value: "ready / 12 docs" },
          { label: "Policy", value: "indexing / 0 docs" },
        ],
        smoke_checks: [
          { label: "FAQ smoke", value: "passed" },
          { label: "Policy smoke", value: "pending" },
        ],
      },
    },
    recent_events: [],
    stages: [
      { stage: "export", label: "Export", status: "completed", status_label: "Completed" },
      { stage: "indexing", label: "Indexing", status: "running", status_label: "Running" },
      { stage: "validation", label: "Validation", status: "pending", status_label: "Waiting" },
    ],
  };

  api.state.lastPayload = payload;
  api.state.selectedStage = "indexing";
  api.renderStageMenu(payload.stages);
  api.renderSelectedStage(payload);

  assert.match(api.refs.stageTimeline.innerHTML, /인덱싱/);
  assert.match(api.refs.stageDetail.innerHTML, /선택한 단계 상세/);
  assert.match(api.refs.stageDetail.innerHTML, /FAQ smoke/);
  assert.match(api.refs.stageDetail.innerHTML, /Policy/);
});

test("validation detail shows check-by-check progress without premature failed or blocked labels", async () => {
  const api = loadApp();
  const payload = {
    run: { site: "food", run_id: "food-demo-validation-005", status: "running", status_label: "Running" },
    process: { running: true, log_path: "/tmp/onmo.log" },
    demo: { status: "disabled", status_label: "GitHub Mode" },
    services: [],
    story: {
      headline: "현재 Validation 단계가 진행 중입니다.",
      summary: "백엔드 런타임 준비를 확인하는 중입니다.",
      current_stage: { stage: "validation", label: "Validation", status: "running", status_label: "Running" },
      focus_stage: { stage: "validation", label: "Validation", status: "running", status_label: "Running" },
      steps: [
        { stage: "export", label: "Export", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "indexing", label: "Indexing", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "validation", label: "Validation", status: "running", status_label: "Running", emphasis: "current" },
      ],
    },
    repair_story: { active: false, headline: "", summary: "", steps: [], failed_stage: "", rewind_to: "" },
    repair: { active: false },
    details: {
      validation: {
        passed: false,
        progress: { total: 4, passed: 1, running: 1, pending: 2, failed: 0, skipped: 0 },
        proofs: [],
        checks: [
          { label: "Backend runtime prep", status: "running", status_label: "진행 중", summary: "fixture manifest 완료" },
          { label: "Backend runtime boot", status: "pending", status_label: "대기", summary: "아직 시작되지 않았습니다." },
          { label: "Widget bundle fetch", status: "pending", status_label: "대기", summary: "백엔드 런타임 준비 이후 실행됩니다." },
          { label: "Flow · list_orders", status: "passed", status_label: "통과", summary: "flow passed" },
        ],
      },
    },
    recent_events: [],
    stages: [
      { stage: "export", label: "Export", status: "completed", status_label: "Completed" },
      { stage: "indexing", label: "Indexing", status: "completed", status_label: "Completed" },
      { stage: "validation", label: "Validation", status: "running", status_label: "Running" },
    ],
  };

  api.state.lastPayload = payload;
  api.state.selectedStage = "validation";
  api.renderStageMenu(payload.stages);
  api.renderSelectedStage(payload);

  assert.match(api.refs.stageDetail.innerHTML, /검증 진행 현황/);
  assert.match(api.refs.stageDetail.innerHTML, /Backend runtime prep/);
  assert.match(api.refs.stageDetail.innerHTML, /Widget bundle fetch/);
  assert.match(api.refs.stageDetail.innerHTML, /Flow · list_orders/);
  assert.match(api.refs.stageDetail.innerHTML, /fixture manifest 완료/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, />Failed</);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, />Blocked</);
});

test("validation detail renders every check row instead of truncating to eight items", async () => {
  const api = loadApp();
  const checks = Array.from({ length: 17 }, (_, index) => ({
    label: `Check ${index + 1}`,
    status: index < 16 ? "passed" : "failed",
    status_label: index < 16 ? "통과" : "실패",
    summary: `summary ${index + 1}`,
  }));
  const payload = {
    run: { site: "food", run_id: "food-demo-validation-rows-017", status: "failed", status_label: "Failed" },
    process: { running: false, log_path: "/tmp/onmo.log" },
    demo: { status: "disabled", status_label: "GitHub Mode" },
    services: [],
    story: {
      headline: "검증이 끝났습니다.",
      summary: "검증 결과를 정리했습니다.",
      current_stage: { stage: "validation", label: "Validation", status: "failed", status_label: "Failed" },
      focus_stage: { stage: "validation", label: "Validation", status: "failed", status_label: "Failed" },
      steps: [{ stage: "validation", label: "Validation", status: "failed", status_label: "Failed", emphasis: "failed" }],
    },
    repair_story: { active: false, headline: "", summary: "", steps: [], failed_stage: "", rewind_to: "" },
    repair: { active: false },
    details: {
      validation: {
        passed: false,
        progress: { total: 17, passed: 16, running: 0, pending: 0, failed: 1, skipped: 0 },
        proofs: [],
        checks,
      },
    },
    recent_events: [],
    stages: [{ stage: "validation", label: "Validation", status: "failed", status_label: "Failed" }],
  };

  api.state.lastPayload = payload;
  api.state.selectedStage = "validation";
  api.renderStageMenu(payload.stages);
  api.renderSelectedStage(payload);

  const rowCount = (api.refs.stageDetail.innerHTML.match(/validation-check-row/g) || []).length;
  assert.equal(rowCount, 17);
  assert.match(api.refs.stageDetail.innerHTML, /전체 17 · 통과 16 · 실패 1/);
});

test("completed validation stage does not keep a live chip in the left rail", async () => {
  const api = loadApp();
  const payload = {
    run: { site: "food", run_id: "food-demo-validation-complete-018", status: "exported", status_label: "Ready" },
    process: { running: false, log_path: "/tmp/onmo.log" },
    demo: { status: "disabled", status_label: "GitHub Mode" },
    story: {
      headline: "검증이 완료되었습니다.",
      summary: "모든 검증이 끝났습니다.",
      current_stage: { stage: "validation", label: "Validation", status: "completed", status_label: "Completed" },
      focus_stage: { stage: "validation", label: "Validation", status: "completed", status_label: "Completed" },
      steps: [
        { stage: "export", label: "Export", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "validation", label: "Validation", status: "completed", status_label: "Completed", emphasis: "current" },
      ],
    },
    repair_story: { active: false, headline: "", summary: "", steps: [], failed_stage: "", rewind_to: "" },
    repair: { active: false },
    details: { validation: { passed: true, progress: { total: 1, passed: 1, running: 0, pending: 0, failed: 0, skipped: 0 }, checks: [] } },
    recent_events: [],
    stages: [
      { stage: "export", label: "Export", status: "completed", status_label: "Completed" },
      { stage: "validation", label: "Validation", status: "completed", status_label: "Completed" },
    ],
  };

  api.state.lastPayload = payload;
  api.state.selectedStage = "validation";
  api.renderStageMenu(payload.stages);

  assert.doesNotMatch(api.refs.stageTimeline.innerHTML, /stage-link-live/);
  assert.doesNotMatch(api.refs.stageTimeline.innerHTML, /진행 중/);
});

test("validation detail renders a primary website open button for exported demo runs", async () => {
  const api = loadApp();
  const payload = {
    run: { site: "bilyeo", run_id: "bilyeo-demo-website-006", status: "exported", status_label: "Ready" },
    process: { running: false, log_path: "/tmp/onmo.log" },
    demo: {
      status: "starting",
      status_label: "Launching bilyeo",
      message: "validated run finished, starting bilyeo live services",
      preview_url: "http://127.0.0.1:3000/bilyeo/",
      primary_action: {
        label: "사이트 열기",
        url: "http://127.0.0.1:3000/bilyeo/",
      },
    },
    services: [],
    story: {
      headline: "Validation이 끝났습니다.",
      summary: "서비스를 시작하고 있습니다.",
      current_stage: { stage: "validation", label: "Validation", status: "completed", status_label: "Completed" },
      focus_stage: { stage: "validation", label: "Validation", status: "completed", status_label: "Completed" },
      steps: [
        { stage: "export", label: "Export", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "indexing", label: "Indexing", status: "completed", status_label: "Completed", emphasis: "default" },
        { stage: "validation", label: "Validation", status: "completed", status_label: "Completed", emphasis: "current" },
      ],
    },
    repair_story: { active: false, headline: "", summary: "", steps: [], failed_stage: "", rewind_to: "" },
    repair: { active: false },
    details: {
      validation: {
        passed: true,
        progress: { total: 4, passed: 4, running: 0, pending: 0, failed: 0, skipped: 0 },
        proofs: [],
        checks: [
          { label: "Backend runtime prep", status: "passed", status_label: "통과", summary: "fixture manifest 완료" },
        ],
      },
    },
    recent_events: [],
    stages: [
      { stage: "export", label: "Export", status: "completed", status_label: "Completed" },
      { stage: "indexing", label: "Indexing", status: "completed", status_label: "Completed" },
      { stage: "validation", label: "Validation", status: "completed", status_label: "Completed" },
    ],
  };

  api.state.lastPayload = payload;
  api.state.selectedStage = "validation";
  api.renderStageMenu(payload.stages);
  api.renderSelectedStage(payload);

  assert.match(api.refs.stageDetail.innerHTML, /사이트 열기/);
  assert.match(api.refs.stageDetail.innerHTML, /http:\/\/127\.0\.0\.1:3000\/bilyeo\//);
});

test("run story graph renders in a dedicated always-visible panel", async () => {
  const api = loadApp();
  const payload = repairPayload();
  api.state.currentRun = {
    site: "bilyeo",
    run_id: "bilyeo-v2-repair-009",
    generated_root: "generated-v2",
  };
  api.state.lastPayload = payload;
  api.state.selectedStage = "analysis";

  api.renderSelectedStage(payload);
  assert.match(api.refs.runStoryShell.innerHTML, /진행 흐름/);
  assert.match(api.refs.runStoryShell.innerHTML, /story-rewind-graph/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Run Story Snapshot/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Narrative Summary/);
});

test("repair snapshot renders a rerun lane and rewind connector", async () => {
  const api = loadApp();
  const payload = repairRerunGraphPayload();
  api.state.lastPayload = payload;
  api.state.selectedStage = "analysis";

  api.renderSelectedStage(payload);

  assert.match(api.refs.runStoryShell.innerHTML, /story-strip-primary/);
  assert.match(api.refs.runStoryShell.innerHTML, /story-strip-rerun/);
  assert.match(api.refs.runStoryShell.innerHTML, /story-rerun-entry-link/);
  assert.match(api.refs.runStoryShell.innerHTML, />repair</);
  assert.match(api.refs.runStoryShell.innerHTML, /분석부터 다시 실행/);
  assert.match(api.refs.runStoryShell.innerHTML, /분석 단계로 되돌아감/);
  assert.match(api.refs.runStoryShell.innerHTML, /검증/);
  assert.doesNotMatch(api.refs.runStoryShell.innerHTML, /오류 상세/);
  assert.doesNotMatch(api.refs.runStoryShell.innerHTML, /진단 판단/);
  assert.doesNotMatch(api.refs.runStoryShell.innerHTML, /현재 상태/);
});

test("rerun lane keeps original stage columns and starts from the rewind stage", async () => {
  const api = loadApp();
  const payload = compileRewindGraphPayload();
  api.state.lastPayload = payload;
  api.state.selectedStage = "compile";

  api.renderSelectedStage(payload);

  const rerunHtml = api.refs.runStoryShell.innerHTML;
  const placeholderCount = (rerunHtml.match(/story-step-placeholder/g) || []).length;

  assert.equal(placeholderCount, 2);
  assert.match(rerunHtml, /story-rerun-entry-link/);
  assert.match(rerunHtml, />repair</);
  assert.match(rerunHtml, /생성부터 다시 실행/);
  assert.match(rerunHtml, /생성/);
  assert.match(rerunHtml, /적용/);
  assert.match(rerunHtml, /추출/);
});

test("rerun lane shows the rewind stage as live when repair is running even if the original current stage already failed", async () => {
  const api = loadApp();
  const payload = repairLiveRerunPayload();
  api.state.lastPayload = payload;
  api.state.selectedStage = "planning";

  api.renderSelectedStage(payload);

  const rerunHtml = api.refs.runStoryShell.innerHTML;
  const rerunLaneHtml = rerunHtml.split('<div class="story-lane story-strip-rerun">')[1] || "";

  assert.match(rerunHtml, /계획부터 다시 실행/);
  assert.match(rerunLaneHtml, /story-step warn current[\s\S]*계획[\s\S]*진행 중/);
  assert.doesNotMatch(rerunLaneHtml, /story-step ok default[\s\S]*생성[\s\S]*완료/);
  assert.match(rerunLaneHtml, /생성[\s\S]*대기/);
  assert.match(rerunLaneHtml, /적용[\s\S]*대기/);
  assert.match(rerunLaneHtml, /추출[\s\S]*대기/);
  assert.match(rerunLaneHtml, /인덱싱[\s\S]*대기/);
  assert.match(rerunLaneHtml, /검증[\s\S]*대기/);
});

test("left rail marks the live current stage separately from the selected stage", async () => {
  const api = loadApp();
  const payload = dashboardPayload();
  api.state.lastPayload = payload;
  api.state.selectedStage = "import";

  api.renderStageMenu(payload.stages);

  assert.match(api.refs.stageTimeline.innerHTML, /stage-link-live/);
  assert.match(api.refs.stageTimeline.innerHTML, /분석/);
  assert.match(api.refs.stageTimeline.innerHTML, /진행 중/);
});

test("cleanup pass removes redundant site and repair status surfaces", async () => {
  const indexPath = path.resolve(__dirname, "../static/index.html");
  const indexHtml = fs.readFileSync(indexPath, "utf8");

  assert.doesNotMatch(indexHtml, /id="run-meta"/);
  assert.doesNotMatch(indexHtml, /Preset Demo/);
  assert.doesNotMatch(indexHtml, /hero-status/);
  assert.doesNotMatch(indexHtml, /id="current-work-banner"/);
  assert.match(indexHtml, /id="run-story-shell"/);

  const api = loadApp();
  const payload = repairPayload();
  api.state.lastPayload = payload;
  api.renderSelectedStage(payload);

  assert.match(indexHtml, /id="run-story-shell"/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Repair Focus Detail/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Narrative Summary/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Current Work/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Run Story Snapshot/);
});

test("github import env file input does not filter hidden dotfiles", async () => {
  const indexPath = path.resolve(__dirname, "../static/index.html");
  const indexHtml = fs.readFileSync(indexPath, "utf8");

  assert.match(indexHtml, /id="github-env-file"/);
  assert.doesNotMatch(indexHtml, /id="github-env-file"[^>]*accept=/);
  assert.match(indexHtml, /Cmd\+Shift\+\./);
});

test("rerun lane removes dashed framing so nodes align with the original columns", async () => {
  const stylesPath = path.resolve(__dirname, "../static/styles.css");
  const styles = fs.readFileSync(stylesPath, "utf8");

  assert.doesNotMatch(styles, /\.story-strip-rerun\s*\{[^}]*border:\s*1px dashed/s);
  assert.doesNotMatch(styles, /\.story-rewind-connector::before[\s\S]*border-top:\s*1px dashed/s);
});

test("repair entry marker reserves vertical space so the label does not overlap the upper lane text", async () => {
  const stylesPath = path.resolve(__dirname, "../static/styles.css");
  const styles = fs.readFileSync(stylesPath, "utf8");

  assert.match(styles, /\.story-rewind-graph\s*\{[^}]*gap:\s*32px/s);
  assert.match(styles, /\.story-strip-rerun\s*\{[^}]*padding-top:\s*28px/s);
});

test("developer log renders the full event count and uses an internal scroll area", async () => {
  const api = loadApp();
  const payload = dashboardPayload();
  payload.recent_events = Array.from({ length: 20 }, (_, index) => ({
    timestamp: `2026-03-27T20:${String(index).padStart(2, "0")}:00+09:00`,
    stage: "analysis",
    summary: `analysis event ${index}`,
    display_summary: `분석 이벤트 ${index}`,
  }));
  api.state.lastPayload = payload;
  api.state.selectedStage = "analysis";

  api.renderSelectedStage(payload);

  const rowCount = (api.refs.stageDetail.innerHTML.match(/raw-log-row/g) || []).length;
  const stylesPath = path.resolve(__dirname, "../static/styles.css");
  const styles = fs.readFileSync(stylesPath, "utf8");

  assert.equal(rowCount, 20);
  assert.match(api.refs.stageDetail.innerHTML, /최근 이벤트 20개/);
  assert.match(styles, /\.raw-log-body\s*\{[^}]*max-height:/s);
  assert.match(styles, /\.raw-log-body\s*\{[^}]*overflow-y:\s*auto/s);
});

test("developer log keeps scroll position across rerenders while polling", async () => {
  const api = loadApp({
    sessionStorage: {
      "onmo.active-run": JSON.stringify({
        site: "bilyeo",
        run_id: "bilyeo-v2-repair-009",
        generated_root: "generated-v2",
      }),
      "onmo.run-ui:bilyeo:bilyeo-v2-repair-009": JSON.stringify({
        selectedStage: "analysis",
        selectionPinned: true,
        rawLogOpen: true,
      }),
    },
  });
  const payload = dashboardPayload();
  payload.recent_events = Array.from({ length: 30 }, (_, index) => ({
    timestamp: `2026-03-27T20:${String(index).padStart(2, "0")}:00+09:00`,
    stage: "analysis",
    summary: `analysis event ${index}`,
    display_summary: `분석 이벤트 ${index}`,
  }));

  api.state.currentRun = {
    site: "bilyeo",
    run_id: "bilyeo-v2-repair-009",
    generated_root: "generated-v2",
  };
  api.state.lastPayload = payload;
  api.restoreRunFromQuery();
  api.renderSelectedStage(payload);

  const firstBody = api.refs.stageDetail.querySelector("[data-raw-log-body]");
  firstBody.scrollTop = 240;
  firstBody.listeners.scroll();

  api.renderSelectedStage(payload);

  const rerenderedBody = api.refs.stageDetail.querySelector("[data-raw-log-body]");
  assert.equal(rerenderedBody.scrollTop, 240);
  assert.equal(
    api.sessionStorage.getItem("onmo.run-ui:bilyeo:bilyeo-v2-repair-009"),
    JSON.stringify({
      selectedStage: "analysis",
      selectionPinned: true,
      rawLogOpen: true,
      rawLogScrollTop: 240,
    })
  );
});

test("developer log auto-follows new entries when the viewer was already at the bottom", async () => {
  const api = loadApp({
    sessionStorage: {
      "onmo.active-run": JSON.stringify({
        site: "bilyeo",
        run_id: "bilyeo-v2-repair-009",
        generated_root: "generated-v2",
      }),
      "onmo.run-ui:bilyeo:bilyeo-v2-repair-009": JSON.stringify({
        selectedStage: "analysis",
        selectionPinned: true,
        rawLogOpen: true,
      }),
    },
  });
  const payload = dashboardPayload();
  payload.recent_events = Array.from({ length: 30 }, (_, index) => ({
    timestamp: `2026-03-27T20:${String(index).padStart(2, "0")}:00+09:00`,
    stage: "analysis",
    summary: `analysis event ${index}`,
    display_summary: `분석 이벤트 ${index}`,
  }));

  api.state.currentRun = {
    site: "bilyeo",
    run_id: "bilyeo-v2-repair-009",
    generated_root: "generated-v2",
  };
  api.state.lastPayload = payload;
  api.restoreRunFromQuery();
  api.renderSelectedStage(payload);

  const firstBody = api.refs.stageDetail.querySelector("[data-raw-log-body]");
  firstBody.scrollTop = firstBody.scrollHeight - firstBody.clientHeight;
  firstBody.listeners.scroll();

  payload.recent_events = Array.from({ length: 35 }, (_, index) => ({
    timestamp: `2026-03-27T21:${String(index).padStart(2, "0")}:00+09:00`,
    stage: "analysis",
    summary: `analysis event ${index}`,
    display_summary: `분석 이벤트 ${index}`,
  }));
  api.renderSelectedStage(payload);

  const rerenderedBody = api.refs.stageDetail.querySelector("[data-raw-log-body]");
  assert.equal(rerenderedBody.scrollTop, rerenderedBody.scrollHeight - rerenderedBody.clientHeight);
});

test("repair layout keeps information ownership split between panels", async () => {
  const api = loadApp();
  const payload = repairPayload();
  api.state.lastPayload = payload;
  api.state.selectedStage = "analysis";

  api.renderSelectedStage(payload);

  assert.match(api.refs.runStoryShell.innerHTML, /처음 실행/);
  assert.match(api.refs.runStoryShell.innerHTML, /분석 단계로 되돌아감/);
  assert.doesNotMatch(api.refs.runStoryShell.innerHTML, /복구 요약/);
  assert.doesNotMatch(api.refs.runStoryShell.innerHTML, /오류 상세/);
  assert.match(api.refs.stageDetail.innerHTML, /오류 상세/);
  assert.match(api.refs.stageDetail.innerHTML, /진단 판단/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /처음 실행/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /분석 단계로 되돌아감/);
});

test("running stage visuals use live animations for emphasis", async () => {
  const stylesPath = path.resolve(__dirname, "../static/styles.css");
  const styles = fs.readFileSync(stylesPath, "utf8");

  assert.match(styles, /@keyframes liveCardPulse/);
  assert.match(styles, /@keyframes liveDotPulse/);
  assert.match(styles, /\.stage-link\.stage-link-live\s*\{[^}]*animation:\s*liveCardPulse/s);
  assert.match(styles, /\.status-badge\.warn\s*\{[^}]*animation:\s*liveChipPulse/s);
  assert.match(styles, /\.story-step\.current \.story-step-node\s*\{[^}]*animation:\s*liveDotPulse/s);
});

test("running analysis renders a single live progress surface instead of summary cards", async () => {
  const api = loadApp();
  const payload = dashboardPayload();
  payload.story.headline = "현재 Analysis 단계가 진행 중입니다.";
  payload.story.summary = "계약 추출 진행 중";
  payload.details.analysis = {
    cards: [{ label: "Backend", value: "django" }],
    live: {
      active_phase: "contract-extraction-r0",
      phase_label: "계약 추출",
      status: "running",
      attempt: 1,
      elapsed_ms: 5425,
      provider: "openai",
      model: "gpt-5.2",
      issue: "",
      metrics: [
        { label: "후보", value: "32" },
        { label: "도구 호출", value: "9" },
      ],
      events: [
        {
          timestamp: "2026-03-27T20:10:00+09:00",
          phase: "candidate_harvest",
          display_summary: "후보 수집 완료",
          details: { status: "completed", candidate_count: 32 },
        },
        {
          timestamp: "2026-03-27T20:10:05+09:00",
          phase: "contract-extraction-r0",
          display_summary: "계약 추출 진행 중",
          details: { status: "running", tool_call_count: 9 },
        },
      ],
    },
  };
  payload.recent_events = [
    {
      timestamp: "2026-03-27T20:10:05+09:00",
      stage: "analysis",
      phase: "contract-extraction-r0",
      event_type: "llm_phase_progress",
      display_summary: "계약 추출 진행 중",
      details: { status: "running", tool_call_count: 9 },
    },
  ];
  api.state.lastPayload = payload;
  api.state.selectedStage = "analysis";

  api.renderSelectedStage(payload);

  assert.equal(api.refs.detailDescription.textContent, "계약 추출 진행 중");
  assert.match(api.refs.stageDetail.innerHTML, /stage-live-shell/);
  assert.match(api.refs.stageDetail.innerHTML, /계약 추출 · 진행/);
  assert.match(api.refs.stageDetail.innerHTML, /후보/);
  assert.match(api.refs.stageDetail.innerHTML, /도구 호출/);
  assert.match(api.refs.stageDetail.innerHTML, /후보 수집 완료/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /fact-card/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /분석 단계 진행 중/);
});

test("running planning updates live phase text on rerender without waiting for completion", async () => {
  const api = loadApp();
  const payload = dashboardPayload();
  payload.story.current_stage = { stage: "planning", label: "Planning", status: "running", status_label: "Running" };
  payload.story.focus_stage = { stage: "planning", label: "Planning", status: "running", status_label: "Running" };
  payload.story.steps = [
    { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed", emphasis: "default" },
    { stage: "planning", label: "Planning", status: "running", status_label: "Running", emphasis: "current" },
  ];
  payload.stages = [
    { stage: "analysis", label: "Analysis", status: "completed", status_label: "Completed" },
    { stage: "planning", label: "Planning", status: "running", status_label: "Running" },
  ];
  payload.details = {
    planning: {
      live: {
        active_phase: "strategy-synthesis",
        phase_label: "전략 후보 정리",
        status: "running",
        attempt: 1,
        elapsed_ms: 8884,
        provider: "openai",
        model: "gpt-5.2",
        issue: "",
        metrics: [{ label: "응답", value: "초안" }],
        events: [
          {
            timestamp: "2026-03-27T20:15:00+09:00",
            phase: "strategy-synthesis",
            display_summary: "전략 후보 정리 진행 중",
            details: { status: "running" },
          },
        ],
      },
    },
  };
  api.state.lastPayload = payload;
  api.state.selectedStage = "planning";
  api.renderSelectedStage(payload);

  assert.equal(api.refs.detailDescription.textContent, "전략 후보 정리 진행 중");
  assert.match(api.refs.stageDetail.innerHTML, /전략 후보 정리 · 진행/);

  payload.details.planning.live = {
    ...payload.details.planning.live,
    active_phase: "binding-selection",
    phase_label: "대상 연결",
    elapsed_ms: 5424,
    metrics: [{ label: "응답", value: "선택 완료" }],
    events: [
      {
        timestamp: "2026-03-27T20:15:06+09:00",
        phase: "binding-selection",
        display_summary: "대상 연결 진행 중",
        details: { status: "running" },
      },
    ],
  };
  payload.recent_events = [
    {
      timestamp: "2026-03-27T20:15:06+09:00",
      stage: "planning",
      phase: "binding-selection",
      event_type: "llm_phase_progress",
      display_summary: "대상 연결 진행 중",
      details: { status: "running" },
    },
  ];
  api.renderSelectedStage(payload);

  assert.equal(api.refs.detailDescription.textContent, "대상 연결 진행 중");
  assert.match(api.refs.stageDetail.innerHTML, /대상 연결 · 진행/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /전략 후보 정리 · 진행/);
});

test("selection auto-follows the live running stage until the user pins another stage", async () => {
  const api = loadApp();
  const payload = dashboardPayload();
  payload.stages = [
    { stage: "analysis", label: "Analysis", status: "running", status_label: "Running" },
    { stage: "planning", label: "Planning", status: "pending", status_label: "Waiting" },
  ];
  api.state.lastPayload = payload;
  api.state.displayStages = [
    { stage: "analysis", label: "Analysis", status: "pending", status_label: "Waiting", summary: "" },
    { stage: "planning", label: "Planning", status: "pending", status_label: "Waiting", summary: "" },
  ];
  api.state.targetStages = payload.stages;
  api.state.selectionPinned = false;
  api.state.selectedStage = "planning";

  api.stepStagePlayback();
  assert.equal(api.state.selectedStage, "analysis");

  api.state.selectionPinned = true;
  api.state.selectedStage = "planning";
  api.state.displayStages = [
    { stage: "analysis", label: "Analysis", status: "pending", status_label: "Waiting", summary: "" },
    { stage: "planning", label: "Planning", status: "pending", status_label: "Waiting", summary: "" },
  ];
  api.state.targetStages = payload.stages;

  api.stepStagePlayback();
  assert.equal(api.state.selectedStage, "planning");
});
