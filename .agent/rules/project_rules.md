---
trigger: always_on
---

## 1. Use uv Not pip

## 2. This is for Mac and Window. So consider it when you code.

# Project Context for Claude

## 1. Project Overview

- **Goal**: [프로젝트의 핵심 목표, 예: 고성능 딥페이크 탐지 모델 개발]
- **Stack**:
  - Language: [Python 3.13]
  - Framework: [PyTorch 2.1, FastAPI]
  - Database: [Qdrant, MySQL]
  - Types: [Strict Type Hinting Required]

## 2. Critical Instructions (DO NOT IGNORE)

- **No Yapping**: Do not apologize. Do not include introductory filler like "Here is the code". Go straight to the solution.
- **Language**: Think in English, Answer in Korean (Technical terms should remain in English).
- **Path**: Always use relative paths from the project root.

## 3. Coding Standards

- **Style Compliance**: Follow **PEP 8** principles but strictly adhere to **Black** formatting (e.g., line length 88, double quotes).
- **Naming Conventions**:
  - Variables/Functions: `snake_case`
  - Classes: `PascalCase`
  - Constants: `SCREAMING_SNAKE_CASE`
- **Docstrings**: MUST use **Google Style Python Docstrings**.
  - Every complex function must list `Args:` and `Returns:` clearly.

## 4. Workflow Rules (CoT & TDD)

- **Step-by-Step Planning**: For complex logic, propose a step-by-step plan and wait for user confirmation before writing code.
- **Modular Design**: Prefer composition over inheritance. Keep functions small (under 50 lines).
- **Refactoring**: If you see legacy or inefficient patterns, flag them and suggest a refactor.

## 5. Security & Performance

- No hardcoded API keys or secrets. Use `.env` files.
- Prioritize vectorization (e.g., pandas/numpy) over loops for data processing.
