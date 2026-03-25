# Slides2 Presentation Deck Design

**Goal:** Build a new HTML presentation deck under `slides2/` for the apparel ecommerce chatbot and onboarding automation presentation, using a premium dashboard-style visual system inspired by the provided white-and-cobalt references.

## Scope

- Output format: standalone HTML deck with `viewer.html` plus per-slide HTML files
- Slide count: 13 slides total
- Structure: 11 main slides + 2 appendix slides
- Content source: the approved presentation storyline and slide scripts provided in the conversation
- Visual source: the provided dashboard reference images

## Visual Direction

### Theme

- Bright white background with generous whitespace
- Deep cobalt as the primary emphasis color
- Soft lavender and cool gray for secondary surfaces
- Rounded dashboard cards with light borders and shallow shadows
- Bold headline typography for opening and closing slides

### Layout Principles

- One headline message per slide
- Large top margin and clear content zoning
- Main content built from 2-column or 3-column dashboard card systems
- Key architecture slides use horizontal flow and segmented capability blocks
- Appendix slides are denser but still maintain the same card language

### Component Language

- Hero blocks with oversized title + short summary
- Metric cards for key claims and outcomes
- Pipeline strips for architecture and onboarding steps
- Split cards for public/protected tools, frontend/backend, and current/future value
- Small synthetic UI widgets to echo the design reference without depending on screenshot assets

## Content Decisions

- The deck will follow the user-approved sequence:
  1. Title
  2. Background
  3. Differentiation
  4. Demo scenario
  5. Moyeo Shop structure
  6. Chatbot architecture
  7. Search and RAG design
  8. Onboarding pipeline
  9. Onboarding operations
  10. Tech selection
  11. Expected impact
  12. Appendix A
  13. Appendix B
- Since no slide-local image assets were provided, the deck will use HTML/CSS dashboard visuals instead of literal screenshots.
- The LLM section will keep the model decision abstract and selection-criteria based.

## Verification Targets

- `slides2/viewer.html` loads the new deck
- `slides2/theme.css` defines the new dashboard design system
- All 13 slide files exist and match the approved narrative
- Representative slides contain the expected titles and structural sections
