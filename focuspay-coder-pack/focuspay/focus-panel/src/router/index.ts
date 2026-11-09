import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('@/components/layout/AppLayout.vue'),
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: 'Дашборд' },
        },
        {
          path: 'requests',
          name: 'requests',
          component: () => import('@/views/RequestsView.vue'),
          meta: { title: 'Заявки' },
        },
        {
          path: 'queue',
          name: 'queue',
          component: () => import('@/views/QueueView.vue'),
          meta: { title: 'Очередь' },
        },
        {
          path: 'search',
          name: 'search',
          component: () => import('@/views/SearchView.vue'),
          meta: { title: 'Поиск' },
        },
        {
          path: 'create',
          name: 'create',
          component: () => import('@/views/CreateView.vue'),
          meta: { title: 'Создать заявку' },
        },
        {
          path: 'output',
          name: 'output',
          component: () => import('@/views/OutputView.vue'),
          meta: { title: 'Вывод средств' },
        },
        {
          path: 'promos',
          name: 'promos',
          component: () => import('@/views/PromosView.vue'),
          meta: { title: 'Промокоды' },
        },
        {
          path: 'shifts',
          name: 'shifts',
          component: () => import('@/views/ShiftsView.vue'),
          meta: { title: 'Смены' },
        },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/ChatView.vue'),
          meta: { title: 'Чат поддержки' },
        },
      ],
    },
  ],
})

export default router
