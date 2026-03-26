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

const ORDER_CS_WIDGET_HOST_CONTRACT = {
  chatbotServerBaseUrl: CHATBOT_SERVER_BASE_URL,
  authBootstrapPath: '/api/chat/auth-token',
  widgetBundlePath: '/widget.js',
  widgetElementTag: 'order-cs-widget',
  mountMode: 'floating_launcher'
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
