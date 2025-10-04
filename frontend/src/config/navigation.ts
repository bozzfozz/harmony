import {
  CircleDot,
  Download,
  LucideIcon,
  Music,
  Radio,
  Settings,
  Sparkles,
  Users
} from 'lucide-react';

export type NavigationService = 'soulseek' | 'matching';

export interface NavigationItem {
  to: string;
  label: string;
  icon: LucideIcon;
  service?: NavigationService;
}

export const navigationItems: NavigationItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: CircleDot },
  { to: '/downloads', label: 'Downloads', icon: Download },
  { to: '/artists', label: 'Artists', icon: Users },
  { to: '/spotify', label: 'Spotify', icon: Music },
  { to: '/soulseek', label: 'Soulseek', icon: Radio, service: 'soulseek' },
  { to: '/matching', label: 'Matching', icon: Sparkles, service: 'matching' },
  { to: '/settings', label: 'Settings', icon: Settings }
];
