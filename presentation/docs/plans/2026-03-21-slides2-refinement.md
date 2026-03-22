# Slides2 Refinement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refine the `slides2/` presentation deck so all slides better support live speaking flow with lower text density and stronger visual hierarchy.

**Architecture:** Keep the existing `slides2/viewer.html` structure and shared `slides2/theme.css`, but update the theme with new layout helpers for contrast-heavy presentation slides. Then revise all slide HTML files to reduce repeated copy, simplify grouping, and prioritize scan-first structures.

**Tech Stack:** Static HTML, CSS, shell-based structural verification

---

### Task 1: Add refined presentation layout helpers

**Files:**
- Modify: `slides2/theme.css`

**Step 1: Write the failing test**

Check for new refinement helpers that do not exist yet.

**Step 2: Run test to verify it fails**

Run: `rg -q "problem-grid|focus-split|support-orbit|chip-cloud" slides2/theme.css`
Expected: FAIL because those helpers are not defined yet

**Step 3: Write minimal implementation**

Add layout helpers for:
- simplified problem framing
- compact architecture splits
- orbit-style support modules
- chip-based appendix summaries

**Step 4: Run test to verify it passes**

Run: `rg -q "problem-grid|focus-split|support-orbit|chip-cloud" slides2/theme.css`
Expected: PASS

### Task 2: Refine high-density core slides

**Files:**
- Modify: `slides2/2.html`
- Modify: `slides2/5.html`
- Modify: `slides2/6.html`
- Modify: `slides2/7.html`
- Modify: `slides2/8.html`
- Modify: `slides2/10.html`

**Step 1: Write the failing test**

Check for new semantic markers that represent the simplified layouts.

**Step 2: Run test to verify it fails**

Run: `rg -q "problem-grid" slides2/2.html && rg -q "service-stack" slides2/5.html && rg -q "chat-compact-flow" slides2/6.html && rg -q "retrieval-split" slides2/7.html && rg -q "pipeline-summary" slides2/8.html && rg -q "tech-pair-grid" slides2/10.html`
Expected: FAIL because those structures do not exist yet

**Step 3: Write minimal implementation**

- reduce copy and repeated banners
- simplify each layout to the dominant spoken point
- strengthen contrast between categories

**Step 4: Run test to verify it passes**

Run the same command again
Expected: PASS

### Task 3: Refine remaining slides for pacing and scanability

**Files:**
- Modify: `slides2/1.html`
- Modify: `slides2/3.html`
- Modify: `slides2/4.html`
- Modify: `slides2/9.html`
- Modify: `slides2/11.html`
- Modify: `slides2/12.html`
- Modify: `slides2/13.html`

**Step 1: Write the failing test**

Check for new structural markers for simplified support layouts.

**Step 2: Run test to verify it fails**

Run: `rg -q "cover-focus" slides2/1.html && rg -q "difference-grid" slides2/3.html && rg -q "scenario-grid" slides2/4.html && rg -q "gate-center" slides2/9.html && rg -q "impact-split" slides2/11.html && rg -q "appendix-chip-grid" slides2/12.html && rg -q "runtime-diagram" slides2/13.html`
Expected: FAIL because those structures do not exist yet

**Step 3: Write minimal implementation**

- improve cover focus and closing emphasis
- reduce line count in appendix slides
- make the operational and appendix slides more diagram-like

**Step 4: Run test to verify it passes**

Run the same command again
Expected: PASS

### Task 4: Verify the refined deck

**Files:**
- Verify: `slides2/theme.css`
- Verify: `slides2/1.html` through `slides2/13.html`

**Step 1: Run structural verification**

Confirm:
- all 13 slides still exist
- new refinement markers exist where expected
- representative title copy remains intact

**Step 2: Review representative markup**

Read back:
- one cover slide
- one problem slide
- one architecture slide
- one onboarding slide
- one appendix slide

Confirm:
- copy is shorter
- grouping is clearer
- the visible emphasis matches the spoken script
