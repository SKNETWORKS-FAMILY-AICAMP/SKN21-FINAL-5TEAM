const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function createElement(id = "") {
  const listeners = {};
  const panels = {};
  let html = "";

  function ensurePanel(key, openPattern) {
    if (!panels[key]) {
      panels[key] = {
        open: false,
        listeners: {},
        addEventListener(type, handler) {
          this.listeners[type] = handler;
        },
      };
    }
    panels[key].open = openPattern.test(html);
    return panels[key];
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
    "current-work-banner",
    "stage-detail",
    "site",
    "repo-url",
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

test("repair mode renders a dedicated hero and uses focus stage details", async () => {
  const api = loadApp();
  const payload = repairPayload();
  api.state.selectedStage = "validation";
  api.state.lastPayload = payload;

  api.renderSelectedStage(payload);

  assert.equal(api.refs.detailTitle.textContent, "계획 -> 분석");
  assert.match(api.refs.stageDetail.innerHTML, /repair-hero/);
  assert.match(api.refs.stageDetail.innerHTML, /Analysis focus card/);
  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /Validation card/);
  assert.match(api.refs.stageDetail.innerHTML, /Run Story Snapshot/);
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
  assert.match(api.refs.stageTimeline.innerHTML, /failed here/);
  assert.match(api.refs.stageTimeline.innerHTML, /re-enter here/);
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
        storySnapshotOpen: true,
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
  assert.equal(api.state.storySnapshotOpen, true);
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
  assert.match(styles, /\.main-panel\s*\{[^}]*grid-template-rows:\s*minmax\(\d+px,\s*auto\)\s+minmax\(0,\s*1fr\)/s);
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

  assert.match(api.refs.stageTimeline.innerHTML, /Indexing/);
  assert.match(api.refs.stageDetail.innerHTML, /Current Stage Detail/);
  assert.match(api.refs.stageDetail.innerHTML, /FAQ smoke/);
  assert.match(api.refs.stageDetail.innerHTML, /Policy/);
});

test("run story snapshot stays open after toggle and rerender", async () => {
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

  const snapshotPanel = api.refs.stageDetail.querySelector("[data-story-snapshot-panel]");
  assert.ok(snapshotPanel, "story snapshot panel should render");

  snapshotPanel.open = true;
  snapshotPanel.listeners.toggle();

  assert.equal(api.state.storySnapshotOpen, true);
  assert.match(
    api.sessionStorage.getItem("onmo.run-ui:bilyeo:bilyeo-v2-repair-009") || "",
    /"storySnapshotOpen":true/
  );

  api.renderSelectedStage(payload);

  const rerenderedPanel = api.refs.stageDetail.querySelector("[data-story-snapshot-panel]");
  assert.equal(rerenderedPanel.open, true);
});

test("repair snapshot renders a rerun lane and rewind connector", async () => {
  const api = loadApp();
  const payload = repairRerunGraphPayload();
  api.state.lastPayload = payload;
  api.state.selectedStage = "analysis";

  api.renderSelectedStage(payload);

  assert.match(api.refs.stageDetail.innerHTML, /story-strip-primary/);
  assert.match(api.refs.stageDetail.innerHTML, /story-strip-rerun/);
  assert.match(api.refs.stageDetail.innerHTML, /story-rewind-connector/);
  assert.match(api.refs.stageDetail.innerHTML, /Re-run from Analysis/);
  assert.match(api.refs.stageDetail.innerHTML, /rewind to Analysis/);
  assert.match(api.refs.stageDetail.innerHTML, /Validation/);
});

test("current work banner is rendered for normal and repair runs", async () => {
  const api = loadApp();
  const normalPayload = dashboardPayload();
  api.state.lastPayload = normalPayload;
  api.state.selectedStage = "analysis";

  api.renderSelectedStage(normalPayload);

  assert.match(api.refs.currentWorkBanner.innerHTML, /Current Work/);
  assert.match(api.refs.currentWorkBanner.innerHTML, /Analysis/);
  assert.match(api.refs.currentWorkBanner.innerHTML, /기존 이벤트를 불러오는 중입니다/);

  const repairPayloadValue = repairPayload();
  api.state.lastPayload = repairPayloadValue;
  api.renderSelectedStage(repairPayloadValue);

  assert.match(api.refs.currentWorkBanner.innerHTML, /계획 -&gt; 분석/);
  assert.match(api.refs.currentWorkBanner.innerHTML, /분석 단계부터 다시 실행하도록 결정했습니다/);
});

test("left rail marks the live current stage separately from the selected stage", async () => {
  const api = loadApp();
  const payload = dashboardPayload();
  api.state.lastPayload = payload;
  api.state.selectedStage = "import";

  api.renderStageMenu(payload.stages);

  assert.match(api.refs.stageTimeline.innerHTML, /stage-link-live/);
  assert.match(api.refs.stageTimeline.innerHTML, /Analysis/);
});

test("cleanup pass removes redundant site and repair status surfaces", async () => {
  const indexPath = path.resolve(__dirname, "../static/index.html");
  const indexHtml = fs.readFileSync(indexPath, "utf8");

  assert.doesNotMatch(indexHtml, /id="run-meta"/);
  assert.doesNotMatch(indexHtml, /Preset Demo/);
  assert.doesNotMatch(indexHtml, /hero-status/);

  const api = loadApp();
  const payload = repairPayload();
  api.state.lastPayload = payload;
  api.renderSelectedStage(payload);

  assert.doesNotMatch(api.refs.stageDetail.innerHTML, /분석 단계로 되감기/);
});
