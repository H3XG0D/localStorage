<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Создать заявку</h1>
        <p class="page-subtitle">Заполните форму для новой заявки</p>
      </div>
    </div>

    <div class="create-layout">
      <!-- Form -->
      <div class="card create-form">
        <!-- Steps -->
        <div class="steps">
          <div
            class="step"
            v-for="(s, i) in steps"
            :key="s"
            :class="{ 'step--done': currentStep > i, 'step--active': currentStep === i }"
          >
            <div class="step-dot">
              <svg v-if="currentStep > i" width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 6l3 3 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span v-else>{{ i + 1 }}</span>
            </div>
            <span class="step-label">{{ s }}</span>
            <div v-if="i < steps.length - 1" class="step-line" :class="{ 'step-line--done': currentStep > i }" />
          </div>
        </div>

        <!-- Step 0: Client -->
        <div v-if="currentStep === 0" class="form-section">
          <h3 class="form-section-title">Данные клиента</h3>
          <div class="grid-2">
            <AppInput v-model="form.lastName" label="Фамилия" placeholder="Иванов" />
            <AppInput v-model="form.firstName" label="Имя" placeholder="Иван" />
          </div>
          <AppInput v-model="form.phone" label="Телефон" placeholder="+7 (___) ___-__-__" type="tel" />
          <AppInput v-model="form.email" label="Email" placeholder="client@example.com" type="email" />
        </div>

        <!-- Step 1: Service -->
        <div v-if="currentStep === 1" class="form-section">
          <h3 class="form-section-title">Услуга</h3>
          <div class="service-grid">
            <button
              v-for="srv in services"
              :key="srv.value"
              class="service-card"
              :class="{ 'service-card--active': form.service === srv.value }"
              @click="form.service = srv.value"
            >
              <span class="service-icon" v-html="srv.icon" />
              <span class="service-name">{{ srv.label }}</span>
              <span class="service-desc">{{ srv.desc }}</span>
            </button>
          </div>
          <AppInput v-model="form.amount" label="Сумма (₽)" placeholder="0.00" type="number" />
          <AppSelect v-model="form.priority" label="Приоритет" :options="priorityOptions" placeholder="Выберите приоритет" />
        </div>

        <!-- Step 2: Comment -->
        <div v-if="currentStep === 2" class="form-section">
          <h3 class="form-section-title">Детали</h3>
          <div class="comment-wrap">
            <label class="comment-label">Комментарий</label>
            <textarea v-model="form.comment" class="comment-field" rows="5" placeholder="Опишите запрос клиента подробнее..." />
          </div>
          <AppSelect v-model="form.assignee" label="Назначить оператора" :options="operatorOptions" placeholder="Автоматически" />
        </div>

        <!-- Navigation -->
        <div class="form-nav">
          <AppButton v-if="currentStep > 0" variant="ghost" @click="currentStep--">← Назад</AppButton>
          <div style="flex:1" />
          <AppButton v-if="currentStep < steps.length - 1" variant="primary" @click="currentStep++" :disabled="!canProceed">
            Далее →
          </AppButton>
          <AppButton v-else variant="primary" :loading="submitting" @click="submit">
            Создать заявку
          </AppButton>
        </div>
      </div>

      <!-- Preview -->
      <div class="create-preview">
        <div class="card">
          <div class="preview-title">Предварительный просмотр</div>
          <div class="preview-rows">
            <div class="preview-row" v-for="row in preview" :key="row.label">
              <span class="preview-label">{{ row.label }}</span>
              <span class="preview-value">{{ row.value || '—' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import AppButton from '@/components/ui/AppButton.vue'

const router = useRouter()
const currentStep = ref(0)
const submitting = ref(false)

const steps = ['Клиент', 'Услуга', 'Детали']

const form = ref({
  lastName: '', firstName: '', phone: '', email: '',
  service: '', amount: '', priority: '', comment: '', assignee: '',
})

const services = [
  { value: 'withdrawal', label: 'Вывод', desc: 'Вывод средств', icon: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><rect x="2" y="4" width="14" height="10" rx="2" stroke="currentColor" stroke-width="1.6"/><path d="M2 7.5h14" stroke="currentColor" stroke-width="1.6"/></svg>` },
  { value: 'deposit', label: 'Пополнение', desc: 'Зачисление средств', icon: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M9 2v14M2 9h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>` },
  { value: 'transfer', label: 'Перевод', desc: 'Между счетами', icon: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M2 6h14M12 2l4 4-4 4M16 12H2M6 8l-4 4 4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>` },
  { value: 'consult', label: 'Консультация', desc: 'Помощь клиенту', icon: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M2 2h14a1 1 0 011 1v8a1 1 0 01-1 1H5l-3 3V3a1 1 0 011-1z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>` },
]

const priorityOptions = [
  { value: 'low', label: 'Низкий' },
  { value: 'normal', label: 'Обычный' },
  { value: 'high', label: 'Высокий' },
]

const operatorOptions = [
  { value: 'elena', label: 'Елена Громова' },
  { value: 'roman', label: 'Роман Фёдоров' },
  { value: 'irina', label: 'Ирина Захарова' },
]

const canProceed = computed(() => {
  if (currentStep.value === 0) return form.value.lastName && form.value.firstName && form.value.phone
  if (currentStep.value === 1) return !!form.value.service
  return true
})

const preview = computed(() => [
  { label: 'Клиент', value: [form.value.lastName, form.value.firstName].filter(Boolean).join(' ') },
  { label: 'Телефон', value: form.value.phone },
  { label: 'Email', value: form.value.email },
  { label: 'Услуга', value: services.find(s => s.value === form.value.service)?.label },
  { label: 'Сумма', value: form.value.amount ? `₽ ${form.value.amount}` : '' },
  { label: 'Приоритет', value: priorityOptions.find(p => p.value === form.value.priority)?.label },
])

async function submit() {
  submitting.value = true
  await new Promise(r => setTimeout(r, 900))
  submitting.value = false
  router.push('/requests')
}
</script>

<style scoped>
.create-layout {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) { .create-layout { grid-template-columns: 1fr; } }

.create-form { display: flex; flex-direction: column; gap: 24px; }

/* Steps */
.steps {
  display: flex; align-items: center; gap: 0;
  padding-bottom: 4px;
}
.step {
  display: flex; align-items: center; gap: 8px;
  flex: 1;
}
.step:last-child { flex: 0; }
.step-dot {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600; color: var(--text-muted);
  flex-shrink: 0; transition: all var(--transition);
}
.step--active .step-dot { border-color: var(--text-primary); color: var(--text-primary); }
.step--done .step-dot { background: var(--text-primary); border-color: var(--text-primary); color: var(--text-inverse); }
.step-label { font-size: 12.5px; color: var(--text-muted); white-space: nowrap; }
.step--active .step-label, .step--done .step-label { color: var(--text-primary); font-weight: 500; }
.step-line { flex: 1; height: 1px; background: var(--border); margin: 0 8px; }
.step-line--done { background: var(--text-primary); }

/* Form section */
.form-section { display: flex; flex-direction: column; gap: 14px; }
.form-section-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }

/* Services */
.service-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.service-card {
  display: flex; flex-direction: column; gap: 4px;
  padding: 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  text-align: left;
  transition: all var(--transition);
}
.service-card:hover { border-color: var(--border-strong); }
.service-card--active { border-color: var(--text-primary); background: rgba(255,255,255,0.04); }
.service-icon { color: var(--text-muted); display: flex; }
.service-name { font-size: 13px; font-weight: 500; color: var(--text-primary); margin-top: 6px; }
.service-desc { font-size: 11.5px; color: var(--text-muted); }

/* Comment */
.comment-wrap { display: flex; flex-direction: column; gap: 5px; }
.comment-label { font-size: 12px; font-weight: 500; color: var(--text-secondary); }
.comment-field {
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  color: var(--text-primary);
  padding: 10px 12px;
  font-size: 13px;
  resize: vertical;
  outline: none;
  transition: border-color var(--transition);
}
.comment-field::placeholder { color: var(--text-muted); }
.comment-field:focus { border-color: var(--text-muted); }

/* Nav */
.form-nav { display: flex; align-items: center; gap: 8px; padding-top: 8px; border-top: 1px solid var(--border); }

/* Preview */
.preview-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 14px; }
.preview-rows { display: flex; flex-direction: column; gap: 10px; }
.preview-row { display: flex; flex-direction: column; gap: 2px; }
.preview-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
.preview-value { font-size: 13px; color: var(--text-primary); }
</style>
