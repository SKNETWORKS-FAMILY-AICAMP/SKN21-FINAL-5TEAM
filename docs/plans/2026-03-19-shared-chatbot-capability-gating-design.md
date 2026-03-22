# Shared Chatbot Capability Gating Design

## Goal

Keep `ecommerce` on the existing full chatbot UX while making onboarded sites consume a restricted shared widget that only exposes order customer-service flows: order lookup, cancel, refund, and exchange.

## Decision

- The shared widget under `chatbot/frontend/shared_widget/` remains the single canonical widget implementation.
- The widget becomes capability-driven instead of site-name-driven.
- `ecommerce` opts into a full capability set.
- Onboarded sites default to an order-CS-only capability set.

## Capability Model

### Full Capability Profile

Used by `ecommerce`.

- `orders_view`
- `orders_cancel`
- `orders_refund`
- `orders_exchange`
- `products_browse`
- `products_purchase`
- `review_write`
- `used_sale`
- `address_search`

### Order CS Capability Profile

Used by onboarded sites by default.

- `orders_view`
- `orders_cancel`
- `orders_refund`
- `orders_exchange`

The shared widget must not render purchase, review, used-sale, or address-search affordances when these capabilities are absent.

## Widget Behavior

### Renderer Gating

- `order_list` remains available in both profiles.
- `product_list` may still be rendered as informational content in onboarding mode, but purchase controls must not be interactive unless `products_purchase` is enabled.
- `review_form`, `used_sale_form`, and `address_search` renderers are only available when the corresponding capability exists.
- Unsupported payloads must fall back to plain text or a benign “not supported on this site” response rather than broken controls.

### Stable Message Identity

The current shared widget must stop relying on render-order or object identity for row keys.

- Prefer explicit `message_id` from normalized payloads.
- Fall back to a deterministic message fingerprint derived from stable fields like type, role, action, order ids, product ids, and text.
- Do not use array index keys.
- Do not use per-render object identity caches as the primary strategy.

This is required so order selections and modal state survive common immutable rerenders.

## Platform Boundaries

### Ecommerce

- `ecommerce/frontend/app/chatbot/chatbotfab.tsx` remains the full wrapper.
- It keeps the existing rich behaviors and passes a full capability set into the shared widget.
- Existing local wrappers such as `OrderListUI`, `ProductListUI`, `ReviewFormUI`, and `UsedSaleFormUI` remain the integration points for ecommerce-specific UX.

### Onboarded Sites

- Generated frontend artifacts remain thin wrappers around the shared widget.
- Default generated capability set is order-CS only.
- Generated wrappers expose the shared host contract:
  - `authBootstrapPath`
  - `chatbotApiBase`
  - shared transport wiring

## Backend Expectations

- The shared chat server remains the single transport and normalization layer.
- Onboarding tool registries should stay aligned with the order-CS-only surface by default.
- The widget must not assume unsupported frontend capabilities just because a normalized payload exists.

## Risks

- `ecommerce` may currently depend on behaviors that are only implicitly preserved inside its wrapper.
- If message identity remains unstable, child-local state loss will continue even after capability gating lands.
- Product-list rendering must avoid no-op purchase controls in onboarding mode, otherwise the shared widget will still look broken despite the new contract.

## Success Criteria

- `ecommerce` still shows the existing rich chatbot UX.
- A generated onboarding site shows only order lookup, cancel, refund, and exchange flows.
- Shared widget default rendering never exposes dead purchase controls in onboarding mode.
- Order selection and product modal state survive rerenders driven by cloned message objects.
