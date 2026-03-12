# SaaS Project Structure Analysis

The SaaS directory follows a **Clean Architecture (Ports and Adapters)** pattern, designed to support multiple ecommerce platforms through a unified interface.

## 🏗 Architecture Overview

The system is divided into three main layers:
1. **Domain**: Core business logic and interface definitions (System-wide contracts).
2. **Adapters**: Concrete implementations for specific external platforms (Implementation details).
3. **Tools**: Interface for higher-level applications (like AI agents) to interact with the domain logic.

---

## 📂 Directory & File Roles

### 1. Domain Layer (`src/domain/`)
Defines the "what" the system does, independent of specific platforms.

| File | Role | Description |
| :--- | :--- | :--- |
| [ecommerce.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/domain/ecommerce.ts) | **Ports & Entities** | Defines core data models (`Product`, `Order`, `User`) and the [EcommerceSupportAdapter](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/domain/ecommerce.ts#L188) interface. |
| [errors.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/domain/errors.ts) | **Error Handling** | Custom error types like `AdapterError` for consistent error reporting across all adapters. |

### 2. Adapter Layer (`src/adapters/`)
Handles the "how" – connecting to external ecommerce platforms (Site-A, Site-B, etc.).

| File/Dir | Role | Description |
| :--- | :--- | :--- |
| `base/` | **Common Logic** | Contains [BaseEcommerceSupportAdapter](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/adapters/base/BaseEcommerceSupportAdapter.ts) which provides shared utilities and the [AdapterRegistry](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/adapters/base/AdapterRegistry.ts) for managing adapters. |
| `site-a/`, `site-b/`, etc. | **Pluggable Adapters** | Platform-specific logic, including Adapters, Clients, and Mappers (e.g., [SiteAAdapter.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/adapters/site-a/SiteAAdapter.ts)). |
| [createRegistry.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/adapters/createRegistry.ts) | **Bootstrap** | A factory function that initializes and registers all available adapters. |

### 3. Tool Layer (`src/tools/`)
Bridges the gap between the domain logic and functional "tools".

| File | Role | Description |
| :--- | :--- | :--- |
| [executeTool.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/tools/executeTool.ts) | **Tool Executor** | Routes functional calls to the correct adapter based on the `siteId`. |

---

## 🔄 Interaction Flow

1. **Input**: A request is received with a `toolName` and a site-specific context ([AuthenticatedContext](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/domain/ecommerce.ts#L10)).
2. **Registry Lookup**: [executeTool.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/tools/executeTool.ts) finds the corresponding adapter.
3. **Adapter Call**: The specific adapter is invoked.
4. **External API**: The adapter's client calls the actual external ecommerce API.
5. **Mapping**: Converts the raw response into standard domain models.
6. **Output**: Returns the standardized result.

---

## 💡 Key Design Patterns
- **Standardized Interfaces**: All external sites are treated uniformly.
- **Data Mapping**: Protects core logic from external API changes.
- **Dependency Inversion**: Core logic depends on abstractions, not implementations.
