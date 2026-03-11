<template>
  <div class="main-page">
    <!-- 카테고리 필터 -->
    <div class="category-bar">
      <button
        v-for="cat in categories"
        :key="cat.value"
        :class="['category-btn', { active: selectedCategory === cat.value }]"
        @click="selectCategory(cat.value)"
      >
        {{ cat.label }}
      </button>
    </div>

    <!-- 상품 그리드 -->
    <div v-if="loading" class="loading-text">상품을 불러오는 중...</div>
    <div v-else-if="products.length === 0" class="empty-text">등록된 상품이 없습니다.</div>
    <div v-else class="product-grid">
      <ProductCard v-for="product in products" :key="product.product_id" :product="product" />
    </div>
  </div>
</template>

<script>
import ProductCard from '../components/ProductCard.vue'
import { productAPI } from '../api'

export default {
  name: 'MainView',
  components: {
    ProductCard
  },
  data() {
    return {
      products: [],
      loading: false,
      selectedCategory: '',
      categories: [
        { label: '전체', value: '' }
      ]
    }
  },
  watch: {
    '$route'(to) {
      if (!to.query.search && to.path === '/') {
        this.selectedCategory = ''
      }
      this.fetchProducts()
    }
  },
  mounted() {
    this.fetchCategories()
    this.fetchProducts()
    this._resetHandler = () => {
      this.selectedCategory = ''
      this.fetchProducts()
    }
    window.addEventListener('reset-home', this._resetHandler)
  },
  beforeUnmount() {
    window.removeEventListener('reset-home', this._resetHandler)
  },
  methods: {
    async fetchCategories() {
      try {
        const res = await productAPI.getCategories()
        const dbCategories = res.data.categories.map(cat => ({ label: cat, value: cat }))
        this.categories = [{ label: '전체', value: '' }, ...dbCategories]
      } catch (err) {
        console.error('카테고리 조회 실패:', err)
      }
    },
    selectCategory(category) {
      this.selectedCategory = category
      this.fetchProducts()
    },
    async fetchProducts() {
      this.loading = true
      try {
        const params = {}
        if (this.selectedCategory) params.category = this.selectedCategory
        if (this.$route.query.search) params.search = this.$route.query.search

        const res = await productAPI.getAll(params)
        this.products = res.data.products
      } catch (err) {
        console.error('상품 조회 실패:', err)
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style scoped>
.category-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.category-btn {
  padding: 8px 20px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background-color: var(--white);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: 'Noto Sans KR', sans-serif;
  color: var(--text);
}

.category-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.category-btn.active {
  background-color: var(--primary);
  color: var(--white);
  border-color: var(--primary);
}

.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 20px;
}

.loading-text,
.empty-text {
  text-align: center;
  padding: 60px 0;
  font-size: 16px;
  color: var(--text-light);
}
</style>
