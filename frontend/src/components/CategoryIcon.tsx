import {
  Car,
  CircleDashed,
  Clapperboard,
  Gift,
  GraduationCap,
  HeartPulse,
  Home,
  Plane,
  Receipt,
  ShoppingBag,
  ShoppingBasket,
  Sparkles,
  Utensils,
  type LucideIcon,
} from 'lucide-react'

const ICONS: Record<string, LucideIcon> = {
  'shopping-basket': ShoppingBasket,
  utensils: Utensils,
  car: Car,
  'shopping-bag': ShoppingBag,
  receipt: Receipt,
  'heart-pulse': HeartPulse,
  clapperboard: Clapperboard,
  plane: Plane,
  'graduation-cap': GraduationCap,
  home: Home,
  sparkles: Sparkles,
  gift: Gift,
  'circle-dashed': CircleDashed,
}

export function CategoryIcon({
  icon,
  color,
  size = 'md',
}: {
  icon?: string | null
  color?: string | null
  size?: 'xs' | 'sm' | 'md' | 'lg'
}) {
  const Icon = (icon && ICONS[icon]) || CircleDashed
  const box = { xs: 'h-6 w-6 rounded-md', sm: 'h-8 w-8 rounded-xl', md: 'h-10 w-10 rounded-2xl', lg: 'h-12 w-12 rounded-2xl' }[size]
  const px = { xs: 13, sm: 15, md: 18, lg: 22 }[size]
  const c = color ?? '#9a958e'
  return (
    <span
      className={`${box} inline-flex shrink-0 items-center justify-center`}
      style={{ background: `${c}22`, color: c, boxShadow: `inset 0 0 0 1px ${c}33` }}
    >
      <Icon size={px} strokeWidth={2.2} />
    </span>
  )
}
