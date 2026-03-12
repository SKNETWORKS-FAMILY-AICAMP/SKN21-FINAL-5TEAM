# Site A Analysis

- frontend framework: Next.js
- backend framework: Express
- routing structure: /products/[id], /cart, /orders
- login method: email/password + JWT
- session storage: httpOnly cookie
- user identity: user_id from /me
- product data access: internal REST API /api/products
- order data access: /api/orders
- api exists: yes
- rendering: SSR + CSR mixed
- widget injection point: global layout footer
- db core tables: users, products, orders, order_items
- media storage: S3 + CDN
- robots/security: bot detection 없음, CSP 제한 약함