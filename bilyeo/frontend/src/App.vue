<template>
  <div id="app">
    <NavBar />
    <main class="main-content">
      <router-view />
    </main>
    <order-cs-widget />
  </div>
</template>

<script>
import NavBar from './components/NavBar.vue'

const CHATBOT_SERVER_BASE_URL = (import.meta.env.VITE_CHATBOT_SERVER_BASE_URL || 'http://127.0.0.1:8100')
  .replace(/\/+$/, '')
const WIDGET_SITE_ID = String(import.meta.env.VITE_WIDGET_SITE_ID || 'bilyeo').trim()
const WIDGET_BRAND_DISPLAY_NAME = String(import.meta.env.VITE_WIDGET_BRAND_DISPLAY_NAME || WIDGET_SITE_ID).trim()
const WIDGET_BRAND_STORE_LABEL = String(import.meta.env.VITE_WIDGET_BRAND_STORE_LABEL || `${WIDGET_BRAND_DISPLAY_NAME} 쇼핑몰`).trim()
const WIDGET_ASSISTANT_TITLE = String(import.meta.env.VITE_WIDGET_ASSISTANT_TITLE || `${WIDGET_BRAND_DISPLAY_NAME} AI 고객상담사`).trim()
const WIDGET_INITIAL_GREETING = String(import.meta.env.VITE_WIDGET_INITIAL_GREETING || `안녕하세요. ${WIDGET_BRAND_DISPLAY_NAME} 챗봇입니다.`).trim()
const CAPABILITY_PROFILE = String(import.meta.env.VITE_CAPABILITY_PROFILE || '').trim()
const ENABLED_RETRIEVAL_CORPORA = String(import.meta.env.VITE_ENABLED_RETRIEVAL_CORPORA || '')
  .split(',')
  .map((token) => token.trim())
  .filter(Boolean)

const ORDER_CS_WIDGET_HOST_CONTRACT = {
  chatbotServerBaseUrl: CHATBOT_SERVER_BASE_URL,
  authBootstrapPath: '/api/chat/auth-token',
  widgetBundlePath: '/widget.js',
  widgetElementTag: 'order-cs-widget',
  mountMode: 'floating_launcher',
  siteId: WIDGET_SITE_ID,
  brandDisplayName: WIDGET_BRAND_DISPLAY_NAME,
  brandStoreLabel: WIDGET_BRAND_STORE_LABEL,
  assistantTitle: WIDGET_ASSISTANT_TITLE,
  initialGreeting: WIDGET_INITIAL_GREETING,
  ...(CAPABILITY_PROFILE ? { capabilityProfile: CAPABILITY_PROFILE } : {}),
  ...(ENABLED_RETRIEVAL_CORPORA.length ? { enabledRetrievalCorpora: ENABLED_RETRIEVAL_CORPORA } : {})
}

function ensureSharedWidgetBundle() {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return
  }

  window.__ORDER_CS_WIDGET_HOST_CONTRACT__ = ORDER_CS_WIDGET_HOST_CONTRACT

  if (document.querySelector('script[data-order-cs-widget-bundle="true"]')) {
    return
  }

  const script = document.createElement('script')
  script.src = `${ORDER_CS_WIDGET_HOST_CONTRACT.chatbotServerBaseUrl}${ORDER_CS_WIDGET_HOST_CONTRACT.widgetBundlePath}`
  script.async = true
  script.dataset.orderCsWidgetBundle = 'true'
  document.head.appendChild(script)
}

export default {
  name: 'App',
  components: {
    NavBar
  },
  mounted() {
    ensureSharedWidgetBundle()
  }
}
</script>
