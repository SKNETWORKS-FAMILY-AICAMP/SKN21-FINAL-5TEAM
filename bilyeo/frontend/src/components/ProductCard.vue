<template>
  <router-link :to="`/product/${product.product_id}`" class="product-card card">
    <div class="product-image">
      <img
        :src="product.image_url || 'https://via.placeholder.com/280x280?text=No+Image'"
        :alt="product.name"
      />
    </div>
    <div class="product-info">
      <div class="product-meta">
        <span class="product-brand">{{ product.brand }}</span>
        <span v-if="product.category" class="product-category">{{ product.category }}</span>
      </div>
      <h3 class="product-name">{{ product.name }}</h3>
      <p class="product-price price">{{ formatPrice(product.price) }}원</p>
    </div>
  </router-link>
</template>

<script>
export default {
  name: 'ProductCard',
  props: {
    product: {
      type: Object,
      required: true
    }
  },
  methods: {
    formatPrice(price) {
      return price?.toLocaleString('ko-KR') || '0'
    }
  }
}
</script>

<style scoped>
.product-card {
  display: block;
  cursor: pointer;
}

.product-image {
  width: 100%;
  aspect-ratio: 1;
  overflow: hidden;
  background-color: #F5F5F5;
}

.product-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.product-card:hover .product-image img {
  transform: scale(1.05);
}

.product-info {
  padding: 16px;
}

.product-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}

.product-brand {
  font-size: 12px;
  color: var(--text-light);
}

.product-category {
  font-size: 11px;
  color: var(--primary-dark);
  background-color: var(--primary-lighter);
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;
}

.product-name {
  font-size: 14px;
  font-weight: 500;
  margin: 4px 0 8px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.product-price {
  font-size: 16px;
}
</style>
