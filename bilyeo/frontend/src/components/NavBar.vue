<template>
  <nav class="navbar">
    <div class="navbar-inner">
      <router-link to="/" class="logo" @click="goHome">Bilyeo</router-link>

      <div class="nav-search">
        <input
          type="text"
          class="search-input"
          placeholder="상품을 검색해보세요"
          v-model="searchQuery"
          @keyup.enter="handleSearch"
        />
        <button class="search-btn" @click="handleSearch">검색</button>
      </div>

      <div class="nav-links">
        <template v-if="auth.isLoggedIn">
          <router-link to="/mypage" class="nav-link">마이페이지</router-link>
          <button class="nav-link logout-btn" @click="logout">로그아웃</button>
        </template>
        <template v-else>
          <router-link to="/login" class="nav-link">로그인</router-link>
        </template>
      </div>
    </div>
  </nav>
</template>

<script>
import { authStore } from '../stores/auth'

export default {
  name: 'NavBar',
  data() {
    return {
      searchQuery: '',
      auth: authStore
    }
  },
  methods: {
    goHome() {
      this.searchQuery = ''
      window.dispatchEvent(new Event('reset-home'))
    },
    handleSearch() {
      const search = this.searchQuery.trim()
      if (search) {
        this.$router.push({ path: '/', query: { search } })
      } else {
        this.$router.push({ path: '/', query: {} }).catch(() => {})
        window.dispatchEvent(new Event('reset-home'))
      }
    },
    logout() {
      authStore.logout()
      this.$router.push('/login')
    }
  }
}
</script>

<style scoped>
.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  background-color: var(--white);
  box-shadow: 0 2px 8px var(--shadow);
  z-index: 1000;
}

.navbar-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}

.logo {
  font-size: 24px;
  font-weight: 700;
  color: var(--primary);
  white-space: nowrap;
}

.nav-search {
  flex: 1;
  max-width: 500px;
  display: flex;
  gap: 8px;
}

.search-input {
  flex: 1;
  padding: 8px 16px;
  border: 1px solid var(--border);
  border-radius: 20px;
  font-size: 14px;
  font-family: 'Noto Sans KR', sans-serif;
}

.search-input:focus {
  outline: none;
  border-color: var(--primary);
}

.search-btn {
  padding: 8px 16px;
  background-color: var(--primary);
  color: var(--white);
  border: none;
  border-radius: 20px;
  font-size: 14px;
  cursor: pointer;
  font-family: 'Noto Sans KR', sans-serif;
}

.search-btn:hover {
  background-color: var(--primary-dark);
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 16px;
  white-space: nowrap;
}

.nav-link {
  font-size: 14px;
  color: var(--text);
  transition: color 0.2s;
}

.nav-link:hover {
  color: var(--primary);
}

.logout-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-family: 'Noto Sans KR', sans-serif;
}
</style>
