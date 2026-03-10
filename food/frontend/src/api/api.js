const BASE_URL = "http://localhost:8000";

export async function fetchProducts() {
  const res = await fetch(`${BASE_URL}/products/`);
  return res.json();
}
