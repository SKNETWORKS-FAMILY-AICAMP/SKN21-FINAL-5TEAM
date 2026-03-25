# Slides2 Presentation Deck Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a new presentation deck in `slides2/` that turns the approved apparel ecommerce chatbot story into a polished dashboard-style HTML slideshow.

**Architecture:** The deck will reuse the existing presentation pattern: a shared `viewer.html`, a shared `theme.css`, and one standalone HTML file per slide. The theme will define a new white-and-cobalt dashboard system, and each slide will compose reusable card and flow components to keep the full deck visually consistent.

**Tech Stack:** Static HTML, CSS, minimal vanilla JavaScript for slide navigation

---

### Task 1: Create the shared theme and viewer shell

**Files:**
- Create: `slides2/theme.css`
- Create: `slides2/viewer.html`

**Step 1: Write the failing test**

Run a shell check that expects `slides2/viewer.html` and `slides2/theme.css` to exist.

**Step 2: Run test to verify it fails**

Run: `for f in slides2/viewer.html slides2/theme.css; do test -f "$f" || exit 1; done`
Expected: FAIL because the files do not exist yet

**Step 3: Write minimal implementation**

- Add a new theme with color tokens, card layouts, flow components, metric blocks, and synthetic dashboard visuals
- Add a viewer that loads 13 slides and supports keyboard navigation

**Step 4: Run test to verify it passes**

Run: `for f in slides2/viewer.html slides2/theme.css; do test -f "$f" || exit 1; done`
Expected: PASS

### Task 2: Create the main presentation slides

**Files:**
- Create: `slides2/1.html`
- Create: `slides2/2.html`
- Create: `slides2/3.html`
- Create: `slides2/4.html`
- Create: `slides2/5.html`
- Create: `slides2/6.html`
- Create: `slides2/7.html`
- Create: `slides2/8.html`
- Create: `slides2/9.html`
- Create: `slides2/10.html`
- Create: `slides2/11.html`

**Step 1: Write the failing test**

Run a shell check that expects representative main slides to exist and contain their headline copy.

**Step 2: Run test to verify it fails**

Run: `test -f slides2/1.html && rg -q "의류 이커머스 고객상담 챗봇" slides2/1.html`
Expected: FAIL because the file does not exist yet

**Step 3: Write minimal implementation**

- Build each main slide using the approved content order
- Keep copy presentation-friendly and visually concise
- Use dashboard-style cards, flows, and metric emphasis instead of plain text-heavy layouts

**Step 4: Run test to verify it passes**

Run: `test -f slides2/1.html && rg -q "의류 이커머스 고객상담 챗봇" slides2/1.html`
Expected: PASS

### Task 3: Create appendix slides

**Files:**
- Create: `slides2/12.html`
- Create: `slides2/13.html`

**Step 1: Write the failing test**

Run a shell check that expects both appendix slides and their section titles.

**Step 2: Run test to verify it fails**

Run: `test -f slides2/13.html && rg -q "온보딩 상세 모듈 맵" slides2/13.html`
Expected: FAIL because the file does not exist yet

**Step 3: Write minimal implementation**

- Appendix A: detailed Moyeo Shop routes, APIs, widget injection points
- Appendix B: onboarding module map and role separation

**Step 4: Run test to verify it passes**

Run: `test -f slides2/13.html && rg -q "온보딩 상세 모듈 맵" slides2/13.html`
Expected: PASS

### Task 4: Verify the full deck structure

**Files:**
- Verify: `slides2/viewer.html`
- Verify: `slides2/theme.css`
- Verify: `slides2/1.html` through `slides2/13.html`

**Step 1: Run structural checks**

Run commands that confirm:
- all 13 slides exist
- the viewer references all 13 slides
- representative slides contain the approved headings

**Step 2: Review generated markup**

Read back the shared theme and representative slides to confirm:
- the white-and-cobalt dashboard style is consistently applied
- opening and ending slides use stronger hero composition
- architecture and onboarding slides use structured flow layouts rather than long text
