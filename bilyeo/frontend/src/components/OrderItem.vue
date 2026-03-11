<template>
  <div class="order-card card">
    <div class="order-header">
      <div class="order-date">{{ formatDate(order.created_at) }}</div>
      <span :class="['badge', statusBadgeClass]">{{ order.status }}</span>
    </div>
    <div class="order-items">
      <div v-for="item in order.items" :key="item.item_id" class="order-item">
        <img
          :src="item.image_url || 'https://via.placeholder.com/60x60?text=No+Image'"
          :alt="item.product_name"
          class="item-image"
        />
        <div class="item-info">
          <p class="item-name">{{ item.product_name }}</p>
          <p class="item-detail">{{ formatPrice(item.price) }}원 x {{ item.quantity }}개</p>
        </div>
      </div>
    </div>
    <div class="order-footer">
      <span class="order-total">총 결제금액: <strong class="price">{{ formatPrice(order.total_price) }}원</strong></span>
    </div>
  </div>
</template>

<script>
export default {
  name: 'OrderItem',
  props: {
    order: {
      type: Object,
      required: true
    }
  },
  computed: {
    statusBadgeClass() {
      const map = {
        '주문완료': 'badge-order',
        '배송중': 'badge-shipping',
        '배송완료': 'badge-delivered',
        '취소': 'badge-cancelled',
        '환불': 'badge-cancelled'
      }
      return map[this.order.status] || 'badge-order'
    }
  },
  methods: {
    formatPrice(price) {
      return price?.toLocaleString('ko-KR') || '0'
    },
    formatDate(dateStr) {
      if (!dateStr) return ''
      const date = new Date(dateStr)
      return `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, '0')}.${String(date.getDate()).padStart(2, '0')}`
    }
  }
}
</script>

<style scoped>
.order-card {
  padding: 20px;
  margin-bottom: 16px;
}

.order-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.order-date {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}

.order-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.order-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.item-image {
  width: 60px;
  height: 60px;
  border-radius: 8px;
  object-fit: cover;
  background-color: #F5F5F5;
}

.item-info {
  flex: 1;
}

.item-name {
  font-size: 14px;
  font-weight: 500;
}

.item-detail {
  font-size: 13px;
  color: var(--text-light);
  margin-top: 2px;
}

.order-footer {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  text-align: right;
}

.order-total {
  font-size: 14px;
}
</style>
