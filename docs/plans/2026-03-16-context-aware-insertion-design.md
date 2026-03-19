# Context-Aware Insertion Design

**Goal:** Reduce hardcoded file-name and append-only behavior so onboarding patch generation works across more site layouts with fewer patch apply failures.

**Current Problem**

The current pipeline reads local code, but most edit targeting still relies on:
- file names like `views.py`, `urls.py`, `App.js`
- hardcoded scoring for `users`, `orders`, `products`
- append-style patch generation

This is good enough for a demo, but brittle in real repositories. We need the generator to understand more of the local structure before deciding where and how to patch.

**Recommended Approach**

Adopt a two-stage content-aware strategy:

1. Build a lightweight symbol/index map from the source tree.
2. Use framework-specific insertion strategies that consume that map.

This keeps the system deterministic and local-only, while moving decision quality away from filename heuristics.

**Alternatives Considered**

1. Expand current filename heuristics.
   - Fastest.
   - Not durable; still breaks on non-standard layouts.

2. Full AST-based patch generation for every framework.
   - Highest ceiling.
   - Too large for the next slice.

3. Lightweight content-aware indexing plus framework-specific insertion rules.
   - Best near-term tradeoff.
   - Improves robustness without a full rewrite.

Recommendation: option 3.

**Architecture**

The next architecture should look like this:

- `site_analyzer.py`
  - still extracts coarse site signals
- `codebase_mapper.py`
  - upgraded to produce a structural index:
    - python functions
    - imports
    - urlpatterns/router markers
    - frontend component markers
- `patch_planner.py`
  - chooses targets from indexed evidence rather than file-name buckets
  - computes insertion anchors for each patch type
- `runtime_runner.py`
  - continues to validate generated unified diffs in runtime workspace

**First Slice Scope**

Only implement Django-oriented context-aware insertion in this slice.

That means:
- identify auth handler candidates from function names and auth signals
- identify urlconf candidates from actual `urlpatterns` and `include(...)` usage
- prefer mount targets from actual frontend component evidence
- generate patch drafts against those preferred targets

Out of scope for this slice:
- full AST rewrites
- framework-specific code synthesis beyond current templates
- LLM-generated patch bodies
- route registration quality for every backend framework

**Data Model Changes**

`codebase-map.json` should be expanded with structured evidence such as:
- `python_functions`
- `python_imports`
- `urlconf_candidates`
- `frontend_component_candidates`
- `auth_candidates`

`patch-proposal.json` should include why a target was selected, based on actual evidence:
- matched function names
- matched auth signals
- matched `urlpatterns`
- matched frontend component markers

**Insertion Strategy**

For Django:
- auth handler target:
  - prefer a Python file containing login/me/session-related functions
- url registration target:
  - prefer a file with `urlpatterns = [...]`
  - prefer project-level urlconf over feature-level urls when multiple options exist
- frontend target:
  - prefer the component containing app shell and route tree

**Failure Handling**

When patch generation cannot find a safe anchor:
- do not guess broadly
- emit fewer targets
- keep the run alive with a narrower patch proposal

This is better than generating a wide patch that later fails in merge simulation.

**Testing Strategy**

Add tests that prove:
- target selection prefers content evidence over simple file names
- project-level Django urlconf can outrank unrelated feature urls
- auth-related views outrank unrelated view modules
- regressions on `food` still pass

**Success Criteria**

This slice is successful if:
- `food-run` style runs reach export more reliably
- generated patch targets are fewer and more relevant
- merge simulation failures from bad target selection decrease
- the new mapper output explains target choice with local evidence
