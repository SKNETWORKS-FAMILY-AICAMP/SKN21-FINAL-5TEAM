import { reactive } from 'vue'

const state = reactive({
  user: JSON.parse(sessionStorage.getItem('user') || 'null')
})

export const authStore = {
  state,

  get isLoggedIn() {
    return !!state.user
  },

  login(user) {
    state.user = user
    sessionStorage.setItem('user', JSON.stringify(user))
  },

  logout() {
    state.user = null
    sessionStorage.removeItem('user')
  }
}
