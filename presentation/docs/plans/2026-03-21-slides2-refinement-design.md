# Slides2 Refinement Design

**Goal:** Refine every slide in `slides2/` so the deck is easier to follow during live delivery, visually aligned with the spoken script, and less cognitively heavy for the audience.

## Review Findings

The current deck has a strong visual theme, but several slides feel denser than they should for an 8-10 minute presentation:

- repeated explanation appears in title, body, cards, and bottom banner
- architecture slides ask the audience to read too many blocks at once
- some appendix slides are list-heavy instead of scan-friendly
- several slides emphasize written explanation where the spoken script should carry the detail

## Refinement Principles

- Keep the existing white-and-cobalt dashboard look
- One message per slide, one dominant visual hierarchy
- Prefer contrast, grouping, and flows over explanatory prose
- Remove repeated wording between lead text, cards, and banners
- Let the presenter speak the nuance and let the slide carry structure

## Slide-by-Slide Direction

### 1. Cover
- Reduce right-side card count
- Increase title dominance
- Keep one supporting service summary and one onboarding summary

### 2. Background
- Reframe into three visual zones: customer problem, operator problem, project goal
- Make the solution bridge explicit instead of repeating the same explanation in cards and banner

### 3. Differentiation
- Keep three core differentiators
- Compress supporting text and move the product framing into a stronger single summary block

### 4. Demo
- Replace speech-heavy feel with clearer scenario contrast
- Make public, logged-in, and operator flow visually distinct at first glance

### 5. Moyeo Shop Structure
- Reduce descriptive card count
- Show the stack as three service layers first, then add just enough supporting detail

### 6. Chatbot Architecture
- Reduce pipeline from six narrative-heavy steps to five compact steps
- Make `Public` vs `Protected` the primary visual contrast
- Keep context as a short side note instead of a full explanatory card

### 7. Retrieval and RAG
- Keep only three visible concepts: text retrieval, image retrieval, chunking rules
- Shorten copy so the audience reads categories, not paragraphs

### 8. Onboarding Pipeline
- Keep the six-step pipeline but shorten every step
- Remove redundant explanation and keep one short supporting message

### 9. Operations
- Put approval gates at the center
- Move Redis, SSE, Slack, and Resume into support modules instead of equally weighted panels

### 10. Tech Selection
- Compress each technology into one line of purpose plus at most two reasons
- Keep the LLM section criteria-based and concise

### 11. Impact
- Group benefits into current value vs expansion value rather than four similar metric tiles
- Keep the final message card as the closing anchor

### 12. Appendix A
- Replace long lists with chips and grouped labels where possible
- Keep it clearly supplemental, not main-deck dense

### 13. Appendix B
- Keep the module map but make the runtime track more diagrammatic and easier to scan

## Verification Targets

- each slide has less repeated explanatory text
- structure slides visibly prioritize grouping and flow over prose
- appendix slides are more scannable than before
- core spoken points remain visually supported by the slide design
