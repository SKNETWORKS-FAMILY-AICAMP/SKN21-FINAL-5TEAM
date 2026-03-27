const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function createElement(id = "") {
  return {
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    className: "",
    disabled: false,
    open: false,
    dataset: {},
    listeners: {},
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    },
    querySelector() {
      return {
        open: false,
        addEventListener() {},
      };
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

function loadApp() {
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
    "stage-detail",
    "site",
    "repo-url",
  ];
  ids.forEach((id) => elements.set(id, createElement(id)));

  const context = {
    console,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    fetch: async () => ({
      ok: true,
      async json() {
        return {
          project_options: [{ site: "bilyeo", source_root: "bilyeo", generated_root: "generated-v2", runtime_root: "runtime-v2" }],
          generated_root_default: "generated-v2",
          runtime_root_default: "runtime-v2",
          preview_url_default: "http://127.0.0.1:3000",
        };
      },
    }),
    document: {
      getElementById(id) {
        return elements.get(id) || createElement(id);
      },
    },
    window: {
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      location: {
        search: "",
        pathname: "/",
        hash: "",
        assign() {},
      },
      history: {
        replaceState() {},
      },
    },
  };
  context.globalThis = context;

  const scriptPath = path.resolve(__dirname, "../static/app.js");
  const source = `${fs.readFileSync(scriptPath, "utf8")}\n;globalThis.__test_api__ = { renderSelectedStage, renderStageMenu, pickDefaultStage, stepStagePlayback, refs, state };`;
  vm.runInNewContext(source, context, { filename: scriptPath });
  return context.__test_api__;
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
