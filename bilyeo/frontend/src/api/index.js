import axios from 'axios'

const APP_BASE = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '') || ''
const API_BASE = (import.meta.env.VITE_API_BASE || `${APP_BASE}/api` || '/api').replace(/\/+$/, '')
const LOGIN_PATH = `${APP_BASE}/login` || '/login'

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json'
  },
  withCredentials: true
})

// 응답 인터셉터: 401 에러 시 로그인 페이지로 이동
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error.config?.url || ''
    if (error.response && error.response.status === 401 && !url.includes('/auth/login')) {
      sessionStorage.removeItem('user')
      window.location.href = LOGIN_PATH
    }
    return Promise.reject(error)
  }
)

// 인증 API
export const authAPI = {
  login: (email, password) => api.post('/auth/login', { email, password })
}

// 상품 API
export const productAPI = {
  getAll: (params) => api.get('/products', { params }),
  getById: (id) => api.get(`/products/${id}`),
  getCategories: () => api.get('/products/categories')
}

// 주문 API
export const orderAPI = {
  getMyOrders: () => api.get('/orders')
}

export default api
