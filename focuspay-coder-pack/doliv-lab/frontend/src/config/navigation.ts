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
  Globe,
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
      { to: '/trader/assets', label: 'Карты', icon: CreditCard, roles: ['trader'] },
      { to: '/trader/payouts', label: 'Выплаты', icon: ClipboardList, roles: ['trader'] },
      { to: '/trader/wallet', label: 'Депозит', icon: Wallet, roles: ['trader'] },
      { to: '/trader/doliv-requests', label: 'Заявки на долив', icon: Droplets, roles: ['trader'] },
      { to: '/trader/expenses', label: 'Затраты', icon: Receipt, roles: ['trader'] },
      { to: '/trader/requisites', label: 'Сессии', icon: History, roles: ['trader'] },
      { to: '/teamlead', label: 'Команда', icon: LayoutDashboard, roles: ['teamlead'] },
      { to: '/doliv', label: 'Главная', icon: LayoutDashboard, roles: ['dolivshchik'] },
      { to: '/admin/requisites', label: 'Реквизиты', icon: CreditCard, roles: ['admin'] },
      { to: '/teamlead/wallet', label: 'Депозит', icon: Wallet, roles: ['teamlead'] },
      { to: '/teamlead/assets', label: 'Карты', icon: CreditCard, roles: ['teamlead'] },
      { to: '/teamlead/requisites', label: 'Сессии', icon: History, roles: ['teamlead'] },
      { to: '/admin/tokens', label: 'Токены / депозиты', icon: Wallet, roles: ['admin'] },
      { to: '/admin/bridge', label: 'Мост / апрувы', icon: Shield, roles: ['admin'] },
      { to: '/admin/platforms', label: 'Площадки', icon: Globe, roles: ['admin'] },
      { to: '/admin/assets', label: 'Карты / затраты', icon: CreditCard, roles: ['admin'] },
      { to: '/admin/doliv-requests', label: 'Заявки на долив', icon: ClipboardList, roles: ['admin'] },
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
  if (role === 'teamlead') return '/teamlead';
  if (role === 'dolivshchik') return '/doliv';
  return '/admin';
}
