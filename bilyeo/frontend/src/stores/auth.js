import { reactive } from 'vue'

const state = reactive({
  token: sessionStorage.getItem('token') || null,
  user: JSON.parse(sessionStorage.getItem('user') || 'null')
})

export const authStore = {
  state,

  get isLoggedIn() {
    return !!state.token
  },

  login(token, user) {
    state.token = token
    state.user = user
    sessionStorage.setItem('token', token)
    sessionStorage.setItem('user', JSON.stringify(user))
  },

  logout() {
    state.token = null
    state.user = null
    sessionStorage.removeItem('token')
    sessionStorage.removeItem('user')
  }
}
