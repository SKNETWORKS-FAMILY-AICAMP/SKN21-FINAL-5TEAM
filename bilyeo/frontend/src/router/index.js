import { createRouter, createWebHistory } from 'vue-router'
import MainView from '../views/MainView.vue'
import LoginView from '../views/LoginView.vue'
import ProductDetail from '../views/ProductDetail.vue'
import MyPageView from '../views/MyPageView.vue'

const routes = [
  { path: '/', name: 'Main', component: MainView },
  { path: '/login', name: 'Login', component: LoginView },
  { path: '/product/:id', name: 'ProductDetail', component: ProductDetail },
  { path: '/mypage', name: 'MyPage', component: MyPageView, meta: { requiresAuth: true } }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

// 인증 가드
router.beforeEach((to, from, next) => {
  if (to.meta.requiresAuth) {
    const token = sessionStorage.getItem('user')
    if (!token) {
      next({ name: 'Login' })
      return
    }
  }
  next()
})

export default router
