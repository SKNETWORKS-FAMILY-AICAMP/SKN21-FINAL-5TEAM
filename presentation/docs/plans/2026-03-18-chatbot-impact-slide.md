# Chatbot Impact Slides Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild `slides/3.html` and refine `slides/4.html` into a connected customer-support AI narrative covering deployment background and measurable impact.

**Architecture:** Keep both files as standalone HTML slides and align them around the same grayscale dashboard visual system. Slide 3 will introduce the operational reasons for AI support adoption, and slide 4 will continue with the impact metrics plus a small source caption.

**Tech Stack:** Static HTML, inline CSS, Tailwind CDN, Font Awesome CDN, Google Fonts

---

### Task 1: Rework `slides/3.html` into deployment background

**Files:**
- Modify: `slides/3.html`

**Step 1: Define the new copy**

Set the slide copy to a direct transition into impact metrics:
- eyebrow: `DEPLOYMENT CONTEXT` or equivalent
- title: `고객상담 챗봇` / `도입 배경`
- body: short explanation that support teams face repeat workload, quality variance, and training burden
- cards: four background drivers linked to slide 4 outcomes

**Step 2: Update layout**

Replace the old equal problem grid with a layout visually related to slide 4:
- one dark highlighted card
- three lighter supporting cards

**Step 3: Adjust visual hierarchy**

Use rounded cards, soft gradient background, ring decoration, and monochrome accent treatment so it reads as the lead-in slide to slide 4.

### Task 2: Refine `slides/4.html`

**Files:**
- Modify: `slides/4.html`

**Step 1: Add source caption**

Place a small caption in the lower-left corner with concise source wording suitable for presentation output.

**Step 2: Keep impact dashboard intact**

Retain the existing four impact metrics and layout hierarchy while ensuring the new source caption does not disrupt the composition.

### Task 3: Verify updated slide markup

**Files:**
- Verify: `slides/3.html`
- Verify: `slides/4.html`

**Step 1: Search for expected copy**

Run content checks to confirm:
- `slides/3.html` includes the new title and card labels
- `slides/4.html` includes the source caption and impact metrics

**Step 2: Review rendered structure by markup**

Read both files back to ensure:
- slide 3 and slide 4 have consistent visual language
- old generic problem-definition copy no longer remains in slide 3
- source caption is placed in the left section of slide 4
