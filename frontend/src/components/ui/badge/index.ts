import { cva, type VariantProps } from 'class-variance-authority'

export { default as Badge } from './Badge.vue'

export const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium leading-4 transition-colors focus:outline-none focus:ring-2 focus:ring-ring',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'text-foreground',
        success: 'border-emerald-700/20 bg-emerald-700/10 text-emerald-800 dark:text-emerald-300',
        warning: 'border-amber-700/20 bg-amber-700/10 text-amber-800 dark:text-amber-300',
        destructive: 'border-red-700/20 bg-red-700/10 text-red-800 dark:text-red-300',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export type BadgeVariants = VariantProps<typeof badgeVariants>
