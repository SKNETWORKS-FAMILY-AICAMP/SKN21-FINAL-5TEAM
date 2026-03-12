<template>
  <div class="login-page">
    <div class="auth-card card">
      <h2 class="auth-title">로그인</h2>
      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label>이메일</label>
          <input type="email" class="input-field" v-model="email" placeholder="이메일을 입력하세요" required />
        </div>
        <div class="form-group">
          <label>비밀번호</label>
          <input type="password" class="input-field" v-model="password" placeholder="비밀번호를 입력하세요" required />
        </div>
        <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>
        <button type="submit" class="btn btn-primary btn-full" :disabled="loading">
          {{ loading ? '로그인 중...' : '로그인' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script>
import { authAPI } from '../api'
import { authStore } from '../stores/auth'

export default {
  name: 'LoginView',
  data() {
    return {
      email: '',
      password: '',
      errorMsg: '',
      loading: false
    }
  },
  methods: {
    async handleLogin() {
      this.errorMsg = ''
      this.loading = true
      try {
        const res = await authAPI.login(this.email, this.password)
        authStore.login(res.data.user)
        this.$router.push('/')
      } catch (err) {
        this.errorMsg = err.response?.data?.error || '로그인에 실패했습니다.'
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: calc(100vh - 120px);
}

.auth-card {
  width: 100%;
  max-width: 420px;
  padding: 40px;
}

.auth-title {
  text-align: center;
  font-size: 24px;
  font-weight: 700;
  color: var(--primary-dark);
  margin-bottom: 32px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 6px;
  color: var(--text);
}

.btn-full {
  width: 100%;
  padding: 14px;
  font-size: 16px;
  margin-top: 8px;
}

.error-msg {
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 12px;
}

</style>
