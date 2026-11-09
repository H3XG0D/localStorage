import {
  LayoutDashboard,
  CreditCard,
  ClipboardList,
  Droplets,
  Receipt,
  Users,
  BarChart3,
  TrendingUp,
  Trophy,
  Wallet,
  FileText,
  Shield,
  Settings,
  History,
  LucideIcon,
} from 'lucide-react';
import { UserRole } from '../api/client';

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  roles: UserRole[];
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const navigation: NavGroup[] = [
  {
    title: 'ГЛАВНОЕ',
    items: [
      { to: '/owner', label: 'Главная', icon: LayoutDashboard, roles: ['owner'] },
      { to: '/owner/admins', label: 'Администраторы', icon: Shield, roles: ['owner'] },
      { to: '/admin', label: 'Главная', icon: LayoutDashboard, roles: ['admin'] },
      { to: '/trader', label: 'Главная', icon: LayoutDashboard, roles: ['trader'] },
      { to: '/doliv', label: 'Главная', icon: LayoutDashboard, roles: ['dolivshchik'] },
      { to: '/admin/requisites', label: 'Реквизиты', icon: CreditCard, roles: ['admin'] },
      { to: '/trader/requisites', label: 'Реквизиты', icon: CreditCard, roles: ['trader'] },
      { to: '/admin/doliv-requests', label: 'Заявки на долив', icon: ClipboardList, roles: ['admin'] },
      { to: '/trader/doliv-requests', label: 'Заявки на долив', icon: ClipboardList, roles: ['trader'] },
      { to: '/admin/dolivs', label: 'Доливы', icon: Droplets, roles: ['admin'] },
      { to: '/doliv/history', label: 'История доливов', icon: History, roles: ['dolivshchik'] },
      { to: '/admin/receipts', label: 'Чеки', icon: Receipt, roles: ['admin'] },
      { to: '/admin/employees', label: 'Сотрудники', icon: Users, roles: ['admin'] },
    ],
  },
  {
    title: 'АНАЛИТИКА',
    items: [
      { to: '/owner/stats', label: 'Статистика', icon: BarChart3, roles: ['owner'] },
      { to: '/owner/analytics', label: 'Аналитика', icon: TrendingUp, roles: ['owner'] },
      { to: '/owner/ratings', label: 'Рейтинги', icon: Trophy, roles: ['owner'] },
      { to: '/owner/employees', label: 'Сотрудники', icon: Users, roles: ['owner'] },
      { to: '/admin/stats', label: 'Статистика', icon: BarChart3, roles: ['admin'] },
      { to: '/admin/analytics', label: 'Аналитика', icon: TrendingUp, roles: ['admin'] },
      { to: '/admin/ratings', label: 'Рейтинги', icon: Trophy, roles: ['admin'] },
    ],
  },
  {
    title: 'ФИНАНСЫ',
    items: [
      { to: '/admin/salaries', label: 'Зарплаты и проценты', icon: Wallet, roles: ['admin'] },
      { to: '/admin/statements', label: 'Ведомости', icon: FileText, roles: ['admin'] },
    ],
  },
  {
    title: 'НАСТРОЙКИ',
    items: [
      { to: '/admin/users', label: 'Пользователи', icon: Users, roles: ['admin'] },
      { to: '/admin/roles', label: 'Роли и права', icon: Shield, roles: ['admin'] },
      { to: '/admin/settings', label: 'Настройки', icon: Settings, roles: ['admin'] },
    ],
  },
];

export function getNavForRole(role: UserRole): NavGroup[] {
  return navigation
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => item.roles.includes(role)),
    }))
    .filter((group) => group.items.length > 0);
}

export function getHomePath(role: UserRole): string {
  if (role === 'owner') return '/owner';
  if (role === 'trader') return '/trader';
  if (role === 'dolivshchik') return '/doliv';
  return '/admin';
}
