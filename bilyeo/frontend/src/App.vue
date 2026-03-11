<template>
  <div id="app">
    <NavBar />
    <main class="main-content">
      <router-view />
    </main>
    <ChatBot />
  </div>
</template>

<script>
import NavBar from './components/NavBar.vue'
import ChatBot from './components/ChatBot.vue'

export default {
  name: 'App',
  components: {
    NavBar,
    ChatBot
  }
}
</script>
