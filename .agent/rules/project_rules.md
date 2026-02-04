---
trigger: always_on
---

# Project Context for Claude

## 1. Project Overview

- **Goal**: [프로젝트의 핵심 목표, 예: 고성능 딥페이크 탐지 모델 개발]
- **Stack**:
  - Language: [Python 3.13]
  - Framework: [PyTorch 2.1, FastAPI]
  - Database: [Qdrant, MySQL]
  - Types: [Strict Type Hinting Required]

## 2. Critical Instructions

- **Interaction Style**: Be direct, cold, and professional. No fluff ("I hope this helps", "Certainly!").
- **Language**:
  - **Think in English** to maximize logic quality.
  - **Output in Korean** for explanations.
  - **Keep Technical Terms in English** (e.g., "Dependency Injection", "Gradient Descent" -> do not translate these).
- **Code Output**:
  - Never output "lazy" code snippets (e.g., `... rest of the code ...`).
  - Always provide the **complete** function or class context so it can be copied/pasted directly.
  - If a file is too long, strictly specify where to insert the new code.

## 3. Coding Standards

- **Style Compliance**: Follow **PEP 8** principles but strictly adhere to **Black** formatting (e.g., line length 88, double quotes).
- **Naming Conventions**:
  - Variables/Functions: `snake_case`
  - Classes: `PascalCase`
  - Constants: `SCREAMING_SNAKE_CASE`
- **Docstrings**: MUST use **Google Style Python Docstrings**.
  - Every complex function must list `Args:` and `Returns:` clearly.

## 4. Workflow & Thinking Process

- **Deep Reasoning**: Before providing code, you MUST write a brief "Thinking Process" block. Analyze the request, identify potential pitfalls (e.g., race conditions, memory leaks), and choose the best architectural pattern.
- **Blueprint First**: For any change involving >2 files or complex logic:
  1. Propose the folder structure/file names.
  2. Define function signatures and data structures (Pydantic models) first.
  3. Wait for confirmation if the change is significant.
- **Atomic Implementation**: Break down large tasks into small, testable steps. Do not output 300 lines of code at once.
- **Self-Correction**: Before finishing the response, ask yourself: "Is this code optimized? Does it handle edge cases (e.g., empty lists, API timeouts)?"

## 5. Tech Stack & Best Practices

- **Package Management**: Always use `uv` for dependency management (e.g., `uv add package`).
- **Web/API**: Use **FastAPI** with strict `async/await` patterns. Avoid blocking I/O operations.
- **Data Validation**: **Pydantic v2** is mandatory for all data schemas (API requests, DB models). Do not use raw dictionaries for structured data.
- **Database/RAG**:
  - Use **Qdrant** for vector storage.
  - Use **LangSmith** for tracing and debugging LLM chains.
- **Performance**:
  - Prefer vectorization (NumPy/Pandas) over Python loops.
  - Use specific typing (e.g., `List[int]`, `Optional[str]`) over `Any`.
