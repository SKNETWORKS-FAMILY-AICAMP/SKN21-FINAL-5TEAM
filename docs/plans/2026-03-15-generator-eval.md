# Generator Eval Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `Generator` 역할의 `proposed_files`와 `proposed_patches` 품질을 golden fixture와 rule-based rubric으로 평가하는 러너를 구현한다.

**Architecture:** `chatbot/tests/onboarding/goldens/generator/` 아래 fixture를 두고, `Generator` role runner에 fixture input을 넣어 나온 proposal을 expected/forbidden 규칙과 비교한다. 결과는 JSON 리포트와 pytest 회귀 테스트로 함께 확인한다.

**Tech Stack:** Python, pytest, existing onboarding role runner, JSON fixtures

---

### Task 1: Golden Fixture Contract

**Files:**
- Create: `chatbot/src/onboarding/generator_eval.py`
- Test: `chatbot/tests/onboarding/test_generator_eval_contract.py`

**Step 1: Write the failing test**

아래를 검증한다.

- fixture 모델이 `id`, `site`, `input`, `expected`, `forbidden`을 가진다
- `expected.proposed_files`, `expected.proposed_patches`가 리스트다
- 잘못된 fixture는 validation error를 낸다

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_eval_contract.py -v`

**Step 3: Write minimal implementation**

Pydantic 모델과 fixture loader를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_eval_contract.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/generator_eval.py chatbot/tests/onboarding/test_generator_eval_contract.py
git commit -m "onboarding: add generator eval fixture contract"
```

### Task 2: Golden Fixtures

**Files:**
- Create: `chatbot/tests/onboarding/goldens/generator/food-auth-and-frontend.json`
- Create: `chatbot/tests/onboarding/goldens/generator/bilyeo-basic.json`
- Create: `chatbot/tests/onboarding/goldens/generator/ecommerce-basic.json`
- Test: `chatbot/tests/onboarding/test_generator_golden_fixtures.py`

**Step 1: Write the failing test**

fixture 디렉터리의 모든 JSON이 contract를 통과하는지 검증한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_golden_fixtures.py -v`

**Step 3: Write minimal fixtures**

초기 3개 fixture를 만든다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_golden_fixtures.py -v`

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding/goldens/generator chatbot/tests/onboarding/test_generator_golden_fixtures.py
git commit -m "onboarding: add generator golden fixtures"
```

### Task 3: Rule-Based Rubric

**Files:**
- Modify: `chatbot/src/onboarding/generator_eval.py`
- Test: `chatbot/tests/onboarding/test_generator_rubric.py`

**Step 1: Write the failing test**

아래를 검증한다.

- `missing_files`
- `extra_files`
- `missing_patches`
- `extra_patches`
- `forbidden_hits`
- 모두 비어 있으면 `pass`

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_rubric.py -v`

**Step 3: Write minimal implementation**

rubric 계산 함수와 result model을 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_rubric.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/generator_eval.py chatbot/tests/onboarding/test_generator_rubric.py
git commit -m "onboarding: add generator eval rubric"
```

### Task 4: Eval Runner

**Files:**
- Modify: `chatbot/src/onboarding/generator_eval.py`
- Create: `chatbot/scripts/run_generator_eval.py`
- Test: `chatbot/tests/onboarding/test_generator_eval_runner.py`

**Step 1: Write the failing test**

아래를 검증한다.

- fixture 디렉터리를 순회
- 각 fixture마다 Generator role 실행
- 결과 JSON 생성
- pass/fail summary 출력

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_eval_runner.py -v`

**Step 3: Write minimal implementation**

role runner 주입 가능한 eval runner와 CLI를 추가한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_eval_runner.py -v`

**Step 5: Commit**

```bash
git add chatbot/src/onboarding/generator_eval.py chatbot/scripts/run_generator_eval.py chatbot/tests/onboarding/test_generator_eval_runner.py
git commit -m "onboarding: add generator eval runner"
```

### Task 5: Regression Test for Current Generator

**Files:**
- Create: `chatbot/tests/onboarding/test_generator_golden_regression.py`

**Step 1: Write the failing test**

현재 deterministic generator 또는 injected fake LLM generator가 fixture를 통과하는지 검증한다.

**Step 2: Run test to verify it fails**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_golden_regression.py -v`

**Step 3: Write minimal implementation**

기본 generator path를 eval runner에 연결한다.

**Step 4: Run test to verify it passes**

Run: `uv run pytest --noconftest chatbot/tests/onboarding/test_generator_golden_regression.py -v`

**Step 5: Commit**

```bash
git add chatbot/tests/onboarding/test_generator_golden_regression.py
git commit -m "onboarding: add generator golden regression"
```

### Task 6: Verification

**Files:**
- Modify as needed from earlier tasks

**Step 1: Run focused eval tests**

Run:

```bash
uv run pytest --noconftest chatbot/tests/onboarding/test_generator_eval_contract.py chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_generator_rubric.py chatbot/tests/onboarding/test_generator_eval_runner.py chatbot/tests/onboarding/test_generator_golden_regression.py -q
```

Expected: PASS

**Step 2: Run full onboarding tests**

Run:

```bash
uv run pytest --noconftest chatbot/tests/onboarding -q
```

Expected: PASS

**Step 3: Run compile verification**

Run:

```bash
uv run python -m py_compile chatbot/src/onboarding/*.py chatbot/scripts/run_generator_eval.py chatbot/scripts/run_onboarding_generation.py
```

Expected: no output

**Step 4: Commit**

```bash
git add chatbot/src/onboarding chatbot/tests/onboarding chatbot/scripts/run_generator_eval.py
git commit -m "onboarding: add generator eval harness"
```
