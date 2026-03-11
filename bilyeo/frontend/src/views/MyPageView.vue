<template>
  <div class="mypage">
    <h1 class="page-title">마이페이지</h1>

    <!-- 사용자 정보 -->
    <div class="user-info card" v-if="user">
      <h3>{{ user.name }}님 안녕하세요!</h3>
      <p class="user-email">{{ user.email }}</p>
    </div>

    <!-- 주문 목록 -->
    <h2 class="section-title">주문 내역</h2>
    <div v-if="loading" class="loading-text">주문 내역을 불러오는 중...</div>
    <div v-else-if="orders.length === 0" class="empty-text">주문 내역이 없습니다.</div>
    <div v-else class="order-list">
      <OrderItem v-for="order in orders" :key="order.order_id" :order="order" />
    </div>
  </div>
</template>

<script>
import OrderItem from '../components/OrderItem.vue'
import { orderAPI } from '../api'
import { authStore } from '../stores/auth'

export default {
  name: 'MyPageView',
  components: {
    OrderItem
  },
  data() {
    return {
      orders: [],
      loading: false
    }
  },
  computed: {
    user() {
      return authStore.state.user
    }
  },
  mounted() {
    this.fetchOrders()
  },
  methods: {
    async fetchOrders() {
      this.loading = true
      try {
        const res = await orderAPI.getMyOrders()
        this.orders = res.data.orders
      } catch (err) {
        console.error('주문 조회 실패:', err)
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.user-info {
  padding: 24px;
  margin-bottom: 32px;
}

.user-info h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--primary-dark);
}

.user-email {
  font-size: 14px;
  color: var(--text-light);
  margin-top: 4px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 16px;
}

.loading-text,
.empty-text {
  text-align: center;
  padding: 40px 0;
  font-size: 14px;
  color: var(--text-light);
}
</style>
