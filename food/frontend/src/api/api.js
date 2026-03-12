const BASE_URL = "http://localhost:8000/api";

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
