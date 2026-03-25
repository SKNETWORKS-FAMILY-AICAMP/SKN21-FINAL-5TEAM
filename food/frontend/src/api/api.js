export const FOOD_API_BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");
const BASE_URL = FOOD_API_BASE ? `${FOOD_API_BASE}/api` : "/api";

export function buildFoodMediaUrl(imagePath) {
  if (!imagePath) return null;
  if (imagePath.startsWith("http://") || imagePath.startsWith("https://")) {
    return imagePath;
  }

  const mediaBase = FOOD_API_BASE ? `${FOOD_API_BASE}/media` : "/media";
  return `${mediaBase.replace(/\/$/, "")}/${String(imagePath).replace(/^\/+/, "")}`;
}

async function parseJSON(response) {
  const text = await response.text();
  if (!text) {
    return { ok: response.ok, data: null };
  }

  try {
    return { ok: response.ok, data: JSON.parse(text) };
  } catch {
    return { ok: response.ok, data: null };
  }
}

export async function login({ email, password }) {
  try {
    const response = await fetch(`${BASE_URL}/users/login/`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    const { ok, data } = await parseJSON(response);

    if (!ok) {
      const message = data?.detail || "로그인에 실패했습니다.";
      return { success: false, message };
    }

    return { success: true, user: data?.user ?? null };
  } catch (error) {
    return { success: false, message: error.message || "네트워크 오류가 발생했습니다." };
  }
}

export async function logout() {
  await fetch(`${BASE_URL}/users/logout/`, {
    method: "POST",
    credentials: "include",
  });
}

export async function fetchMe() {
  try {
    const response = await fetch(`${BASE_URL}/users/me/`, {
      method: "GET",
      credentials: "include",
    });
    const { data } = await parseJSON(response);
    if (!data) {
      return { authenticated: false };
    }
    return data;
  } catch {
    return { authenticated: false };
  }
}

export async function fetchProducts() {
  const response = await fetch(`${BASE_URL}/products/`);
  const payload = await response.json().catch(() => null);
  return payload;
}

export async function fetchOrders() {
  const response = await fetch(`${BASE_URL}/orders/`, {
    method: "GET",
    credentials: "include",
  });
  const { ok, data } = await parseJSON(response);

  if (!ok) {
    throw new Error(data?.detail || "주문 정보를 불러오는 데 실패했습니다.");
  }

  return Array.isArray(data) ? data : [];
}

export async function fetchOrderDetail(orderId) {
  const response = await fetch(`${BASE_URL}/orders/${orderId}/`, {
    method: "GET",
    credentials: "include",
  });
  const { ok, data } = await parseJSON(response);

  if (!ok) {
    throw new Error(data?.detail || "주문 상세를 불러오는 데 실패했습니다.");
  }

  return data;
}

export async function performOrderAction(orderId, action, extra = {}) {
  const response = await fetch(`${BASE_URL}/orders/${orderId}/actions/`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...extra }),
  });
  const { ok, data } = await parseJSON(response);

  if (!ok) {
    throw new Error(data?.detail || "주문 요청 처리 중 오류가 발생했습니다.");
  }

  return data;
}
