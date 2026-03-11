<template>
  <div class="detail-page">
    <div v-if="loading" class="loading-text">상품 정보를 불러오는 중...</div>
    <div v-else-if="!product" class="empty-text">상품을 찾을 수 없습니다.</div>
    <div v-else class="detail-content">
      <div class="detail-image">
        <img
          :src="product.image_url || 'https://via.placeholder.com/500x500?text=No+Image'"
          :alt="product.name"
        />
      </div>
      <div class="detail-info">
        <span class="detail-brand">{{ product.brand }}</span>
        <h1 class="detail-name">{{ product.name }}</h1>
        <p class="detail-price price">{{ formatPrice(product.price) }}원</p>

        <div class="detail-meta">
          <div class="meta-item">
            <span class="meta-label">카테고리</span>
            <span class="meta-value">{{ product.category || '-' }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">재고</span>
            <span class="meta-value">{{ product.stock > 0 ? `${product.stock}개` : '품절' }}</span>
          </div>
        </div>

        <div class="detail-description">
          <h3>상품 설명</h3>
          <p>{{ product.description || '상품 설명이 없습니다.' }}</p>
        </div>

        <button class="btn btn-outline" @click="$router.back()">목록으로 돌아가기</button>
      </div>
    </div>
  </div>
</template>

<script>
import { productAPI } from '../api'

export default {
  name: 'ProductDetail',
  data() {
    return {
      product: null,
      loading: false
    }
  },
  mounted() {
    this.fetchProduct()
  },
  methods: {
    async fetchProduct() {
      this.loading = true
      try {
        const res = await productAPI.getById(this.$route.params.id)
        this.product = res.data.product
      } catch (err) {
        console.error('상품 조회 실패:', err)
      } finally {
        this.loading = false
      }
    },
    formatPrice(price) {
      return price?.toLocaleString('ko-KR') || '0'
    }
  }
}
</script>

<style scoped>
.detail-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 40px;
  max-width: 1000px;
  margin: 0 auto;
}

.detail-image {
  border-radius: 12px;
  overflow: hidden;
  background-color: #F5F5F5;
}

.detail-image img {
  width: 100%;
  height: auto;
  display: block;
}

.detail-brand {
  font-size: 14px;
  color: var(--text-light);
}

.detail-name {
  font-size: 24px;
  font-weight: 700;
  margin: 8px 0 16px;
}

.detail-price {
  font-size: 28px;
  margin-bottom: 24px;
}

.detail-meta {
  display: flex;
  gap: 24px;
  margin-bottom: 24px;
  padding: 16px;
  background-color: var(--primary-lighter);
  border-radius: 8px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-label {
  font-size: 12px;
  color: var(--text-light);
}

.meta-value {
  font-size: 14px;
  font-weight: 500;
}

.detail-description {
  margin-bottom: 32px;
}

.detail-description h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}

.detail-description p {
  font-size: 14px;
  color: var(--text-light);
  line-height: 1.8;
}

.loading-text,
.empty-text {
  text-align: center;
  padding: 60px 0;
  font-size: 16px;
  color: var(--text-light);
}

@media (max-width: 768px) {
  .detail-content {
    grid-template-columns: 1fr;
  }
}
</style>
