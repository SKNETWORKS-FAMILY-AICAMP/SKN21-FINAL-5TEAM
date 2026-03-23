<template>
  <div class="chatbot-wrapper">
    <!-- 채팅창 -->
    <div v-if="isOpen" class="chatbot-window card">
      <div class="chatbot-header">
        <span class="chatbot-title">Bilyeo 챗봇</span>
        <button class="chatbot-close" @click="isOpen = false">&times;</button>
      </div>

      <div class="chatbot-messages" ref="messageArea">
        <div class="chatbot-welcome">안녕하세요! 무엇을 도와드릴까요?</div>
        <div
          v-for="(msg, i) in messages"
          :key="i"
          :class="['chatbot-msg', msg.role === 'user' ? 'msg-user' : 'msg-bot']"
        >
          {{ msg.text }}
        </div>
      </div>

      <div class="chatbot-input-area">
        <input
          type="text"
          class="chatbot-input"
          placeholder="메시지를 입력하세요"
          v-model="input"
          @keyup.enter="sendMessage"
        />
        <button class="chatbot-send" @click="sendMessage">전송</button>
      </div>
    </div>

    <!-- 플로팅 버튼 -->
    <button class="chatbot-fab" @click="isOpen = !isOpen">
      <span v-if="!isOpen">💬</span>
      <span v-else>&times;</span>
    </button>
  </div>
</template>

<script>
export default {
  name: 'ChatBot',
  data() {
    return {
      isOpen: false,
      input: '',
      messages: []
    }
  },
  methods: {
    sendMessage() {
      const text = this.input.trim()
      if (!text) return

      this.messages.push({ role: 'user', text })
      this.input = ''

      // 봇 응답 (UI 껍데기 - 백엔드 미연결)
      setTimeout(() => {
        this.messages.push({ role: 'bot', text: '현재 챗봇 기능을 준비 중입니다.' })
        this.$nextTick(() => {
          const area = this.$refs.messageArea
          if (area) area.scrollTop = area.scrollHeight
        })
      }, 500)

      this.$nextTick(() => {
        const area = this.$refs.messageArea
        if (area) area.scrollTop = area.scrollHeight
      })
    }
  }
}
</script>

<style scoped>
.chatbot-wrapper {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
}

.chatbot-fab {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background-color: var(--primary);
  color: var(--white);
  border: none;
  font-size: 24px;
  cursor: pointer;
  box-shadow: 0 4px 12px var(--shadow);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: auto;
}

.chatbot-fab:hover {
  background-color: var(--primary);
}

.chatbot-window {
  width: 360px;
  height: 480px;
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
  overflow: hidden;
  transform: none !important;
}

.chatbot-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  background-color: var(--primary);
  color: var(--white);
}

.chatbot-title {
  font-size: 15px;
  font-weight: 600;
}

.chatbot-close {
  background: none;
  border: none;
  color: var(--white);
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
}

.chatbot-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background-color: var(--bg);
}

.chatbot-welcome {
  text-align: center;
  font-size: 13px;
  color: var(--text-light);
  padding: 8px 0;
}

.chatbot-msg {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.msg-user {
  align-self: flex-end;
  background-color: var(--primary);
  color: var(--white);
  border-bottom-right-radius: 4px;
}

.msg-bot {
  align-self: flex-start;
  background-color: var(--white);
  color: var(--text);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
}

.chatbot-input-area {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border);
  background-color: var(--white);
}

.chatbot-input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 20px;
  font-size: 14px;
  font-family: 'Noto Sans KR', sans-serif;
  outline: none;
}

.chatbot-input:focus {
  border-color: var(--primary);
}

.chatbot-send {
  padding: 8px 16px;
  background-color: var(--primary);
  color: var(--white);
  border: none;
  border-radius: 20px;
  font-size: 14px;
  cursor: pointer;
  font-family: 'Noto Sans KR', sans-serif;
  white-space: nowrap;
}

.chatbot-send:hover {
  background-color: var(--primary-dark);
}
</style>
