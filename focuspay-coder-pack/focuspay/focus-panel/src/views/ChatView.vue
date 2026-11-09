<template>
  <div class="chat-layout">
    <!-- Conversations sidebar -->
    <div class="chat-sidebar">
      <div class="chat-sidebar-head">
        <span class="chat-sidebar-title">Чат поддержки</span>
        <AppBadge variant="blue" size="sm">{{ unread }} новых</AppBadge>
      </div>
      <div class="chat-search">
        <AppInput v-model="convSearch" placeholder="Поиск..." type="search">
          <template #prefix>
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><circle cx="5.5" cy="5.5" r="4" stroke="currentColor" stroke-width="1.3"/><path d="M9 9l3 3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
          </template>
        </AppInput>
      </div>
      <div class="conv-list">
        <div
          class="conv-item"
          v-for="conv in filteredConvs"
          :key="conv.id"
          :class="{ 'conv-item--active': activeConv?.id === conv.id, 'conv-item--unread': conv.unread > 0 }"
          @click="openConv(conv)"
        >
          <div class="conv-avatar">{{ conv.initials }}</div>
          <div class="conv-info">
            <div class="conv-top">
              <span class="conv-name">{{ conv.name }}</span>
              <span class="conv-time">{{ conv.lastTime }}</span>
            </div>
            <div class="conv-bottom">
              <span class="conv-preview">{{ conv.lastMsg }}</span>
              <span v-if="conv.unread" class="conv-badge">{{ conv.unread }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Messages area -->
    <div class="chat-main" v-if="activeConv">
      <!-- Header -->
      <div class="chat-header">
        <div class="chat-header-info">
          <div class="chat-avatar">{{ activeConv.initials }}</div>
          <div>
            <div class="chat-name">{{ activeConv.name }}</div>
            <div class="chat-status">
              <span class="status-dot" :class="activeConv.online ? 'status-dot--online' : ''" />
              {{ activeConv.online ? 'Онлайн' : 'Офлайн' }}
            </div>
          </div>
        </div>
        <div class="chat-header-actions">
          <AppButton variant="ghost" size="sm" :icon-only="true" title="Заявки клиента">
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M1.5 4h12M1.5 8h8M1.5 12h10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
          </AppButton>
          <AppButton variant="ghost" size="sm" :icon-only="true" title="Закрыть чат">
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M1 1l13 13M14 1L1 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </AppButton>
        </div>
      </div>

      <!-- Messages -->
      <div class="messages-area" ref="messagesEl">
        <div class="messages-date-divider">Сегодня, {{ today }}</div>
        <div
          class="message"
          v-for="msg in activeConv.messages"
          :key="msg.id"
          :class="msg.from === 'operator' ? 'message--out' : 'message--in'"
        >
          <div class="message-bubble">
            <p class="message-text">{{ msg.text }}</p>
            <span class="message-time">{{ msg.time }}</span>
          </div>
        </div>
      </div>

      <!-- Input -->
      <div class="chat-input-area">
        <div class="chat-input-wrap">
          <button class="chat-attach" title="Прикрепить файл">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M13.5 8.5l-6 6a4 4 0 01-5.66-5.66l6.5-6.5a2.5 2.5 0 013.54 3.54L5.37 12.4a1 1 0 01-1.41-1.42L10 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <textarea
            v-model="msgText"
            class="chat-input"
            placeholder="Написать сообщение..."
            rows="1"
            @keydown.enter.exact.prevent="sendMessage"
            @input="autoResize"
            ref="inputEl"
          />
          <button class="chat-send" :class="{ 'chat-send--active': msgText.trim() }" @click="sendMessage">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 8l12-6-5 6 5 6-12-6z" fill="currentColor"/></svg>
          </button>
        </div>
        <p class="chat-hint">Enter — отправить, Shift+Enter — новая строка</p>
      </div>
    </div>

    <!-- Empty state -->
    <div class="chat-empty" v-else>
      <svg width="44" height="44" viewBox="0 0 44 44" fill="none"><path d="M4 4h36a2 2 0 012 2v22a2 2 0 01-2 2H10l-8 8V6a2 2 0 012-2z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>
      <p>Выберите диалог</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppInput from '@/components/ui/AppInput.vue'

const convSearch = ref('')
const msgText = ref('')
const messagesEl = ref<HTMLElement>()
const inputEl = ref<HTMLTextAreaElement>()

const today = new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
const unread = ref(3)

interface Message { id: number; from: 'client' | 'operator'; text: string; time: string }
interface Conversation {
  id: number; name: string; initials: string; lastMsg: string; lastTime: string; unread: number; online: boolean
  messages: Message[]
}

const conversations = ref<Conversation[]>([
  {
    id: 1, name: 'Иван Петров', initials: 'ИП', lastMsg: 'Когда придут деньги?', lastTime: '14:32', unread: 2, online: true,
    messages: [
      { id: 1, from: 'client', text: 'Здравствуйте! Хочу уточнить статус заявки #1042', time: '14:15' },
      { id: 2, from: 'operator', text: 'Добрый день, Иван! Заявка #1042 уже в обработке, средства поступят в течение 30 минут.', time: '14:18' },
      { id: 3, from: 'client', text: 'Отлично, спасибо!', time: '14:20' },
      { id: 4, from: 'client', text: 'Когда придут деньги?', time: '14:32' },
    ],
  },
  {
    id: 2, name: 'Анна Сидорова', initials: 'АС', lastMsg: 'Хорошо, жду', lastTime: '13:58', unread: 0, online: true,
    messages: [
      { id: 1, from: 'client', text: 'Помогите с пополнением счёта', time: '13:45' },
      { id: 2, from: 'operator', text: 'Конечно! Для пополнения перейдите в раздел "Пополнение" и следуйте инструкциям.', time: '13:50' },
      { id: 3, from: 'client', text: 'Хорошо, жду', time: '13:58' },
    ],
  },
  {
    id: 3, name: 'Олег Кузнецов', initials: 'ОК', lastMsg: 'Спасибо за помощь', lastTime: '12:11', unread: 1, online: false,
    messages: [
      { id: 1, from: 'client', text: 'Нужна консультация по переводам', time: '12:00' },
      { id: 2, from: 'operator', text: 'Добрый день! Расскажите подробнее, что именно вас интересует.', time: '12:05' },
      { id: 3, from: 'client', text: 'Спасибо за помощь', time: '12:11' },
    ],
  },
])

const activeConv = ref<Conversation | null>(null)

function openConv(conv: Conversation) {
  activeConv.value = conv
  conv.unread = 0
  unread.value = conversations.value.reduce((sum, c) => sum + c.unread, 0)
  nextTick(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
}

const filteredConvs = computed(() =>
  conversations.value.filter(c =>
    !convSearch.value || c.name.toLowerCase().includes(convSearch.value.toLowerCase())
  )
)

function sendMessage() {
  const text = msgText.value.trim()
  if (!text || !activeConv.value) return
  activeConv.value.messages.push({
    id: Date.now(),
    from: 'operator',
    text,
    time: new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
  })
  activeConv.value.lastMsg = text
  activeConv.value.lastTime = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  msgText.value = ''
  if (inputEl.value) inputEl.value.style.height = 'auto'
  nextTick(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
}

function autoResize(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: calc(100dvh - var(--topbar-h));
  overflow: hidden;
}

/* Sidebar */
.chat-sidebar {
  width: 300px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  overflow: hidden;
}

.chat-sidebar-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 16px 0;
}
.chat-sidebar-title { font-size: 14px; font-weight: 700; color: var(--text-primary); }

.chat-search { padding: 12px 12px 8px; }

.conv-list { flex: 1; overflow-y: auto; }

.conv-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  transition: background var(--transition);
  border-bottom: 1px solid var(--border);
}
.conv-item:hover { background: var(--bg-elevated); }
.conv-item--active { background: var(--bg-elevated); }

.conv-avatar {
  width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0;
  background: var(--bg-overlay); border: 1px solid var(--border-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: var(--text-secondary);
}
.conv-item--unread .conv-avatar { border-color: var(--text-muted); }

.conv-info { flex: 1; min-width: 0; }
.conv-top { display: flex; justify-content: space-between; align-items: baseline; }
.conv-name { font-size: 13px; font-weight: 500; color: var(--text-primary); }
.conv-item--unread .conv-name { font-weight: 600; }
.conv-time { font-size: 11px; color: var(--text-muted); flex-shrink: 0; }

.conv-bottom { display: flex; justify-content: space-between; align-items: center; margin-top: 2px; }
.conv-preview { font-size: 12px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.conv-badge {
  background: var(--text-primary); color: var(--text-inverse);
  font-size: 10px; font-weight: 700;
  width: 18px; height: 18px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-left: 6px;
}

/* Main chat area */
.chat-main {
  flex: 1; display: flex; flex-direction: column; min-width: 0; overflow: hidden;
  background: var(--bg-base);
}

.chat-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  flex-shrink: 0;
}
.chat-header-info { display: flex; align-items: center; gap: 10px; }
.chat-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  background: var(--bg-elevated); border: 1px solid var(--border-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: var(--text-secondary);
  flex-shrink: 0;
}
.chat-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.chat-status { display: flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--text-muted); margin-top: 1px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--border-strong); flex-shrink: 0; }
.status-dot--online { background: var(--green); box-shadow: 0 0 0 2px var(--green-bg); }
.chat-header-actions { display: flex; gap: 4px; }

/* Messages */
.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.messages-date-divider {
  text-align: center;
  font-size: 11px;
  color: var(--text-muted);
  margin: 8px 0;
}

.message { display: flex; }
.message--out { justify-content: flex-end; }
.message--in  { justify-content: flex-start; }

.message-bubble {
  max-width: 68%;
  padding: 9px 13px;
  border-radius: var(--radius-lg);
  display: flex; flex-direction: column; gap: 4px;
}
.message--in  .message-bubble { background: var(--bg-surface); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
.message--out .message-bubble { background: var(--bg-elevated); border: 1px solid var(--border-strong); border-bottom-right-radius: 4px; }

.message-text { font-size: 13.5px; color: var(--text-primary); line-height: 1.5; word-break: break-word; }
.message-time { font-size: 10.5px; color: var(--text-muted); align-self: flex-end; }

/* Input */
.chat-input-area {
  padding: 12px 16px 14px;
  border-top: 1px solid var(--border);
  background: var(--bg-surface);
  flex-shrink: 0;
}
.chat-input-wrap {
  display: flex; align-items: flex-end; gap: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  padding: 6px 8px;
  transition: border-color var(--transition);
}
.chat-input-wrap:focus-within { border-color: var(--text-muted); }

.chat-attach {
  color: var(--text-muted); display: flex; align-items: center;
  padding: 5px; cursor: pointer; flex-shrink: 0;
  transition: color var(--transition);
}
.chat-attach:hover { color: var(--text-primary); }

.chat-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 13.5px;
  resize: none;
  max-height: 120px;
  overflow-y: auto;
  line-height: 1.5;
  padding: 4px 0;
}
.chat-input::placeholder { color: var(--text-muted); }

.chat-send {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px;
  border-radius: var(--radius);
  color: var(--text-muted);
  transition: all var(--transition);
  cursor: pointer; flex-shrink: 0;
}
.chat-send--active { background: var(--text-primary); color: var(--text-inverse); }

.chat-hint { font-size: 10.5px; color: var(--text-muted); margin-top: 6px; padding: 0 4px; }

/* Empty state */
.chat-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 14px; color: var(--text-muted); font-size: 13.5px;
  background: var(--bg-base);
}

@media (max-width: 700px) {
  .chat-sidebar { width: 100%; position: absolute; z-index: 5; }
  .chat-main { position: absolute; inset: 0; }
}
</style>
