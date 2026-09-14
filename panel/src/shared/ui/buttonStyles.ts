/**
 * What a button looks like, separated from what a button *is*.
 *
 * Two places need the look without the `<button>`: a `<Link>` that navigates,
 * and an `<a href>` whose response is a download. Wrapping a `<Button>` in a
 * `<Link>` nests one interactive element inside another — invalid HTML, and it
 * reads badly to a screen reader — while copying the classes into a module
 * grows the parallel Button that CONVENTIONS-CLIENT.md §1 forbids.
 *
 * It lives in its own file rather than beside `Button` so that `primitives.tsx`
 * keeps exporting components and nothing else, which is what React Fast Refresh
 * needs to swap a component without remounting the tree.
 */
import { cn } from '@/shared/lib/cn'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md'

export const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-accent-fg hover:opacity-90 shadow-xs',
  secondary: 'bg-surface-2 text-text hover:bg-border',
  ghost: 'bg-transparent text-muted hover:bg-surface-2 hover:text-text',
  danger: 'bg-bad text-accent-fg hover:opacity-90',
}

export const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-10 px-4 text-sm',
}

/** `Button` is built from this, so an anchor styled with it cannot drift. */
export function buttonClasses(
  { variant = 'primary', size = 'md' }: { variant?: ButtonVariant; size?: ButtonSize } = {},
  className?: string,
): string {
  return cn(
    'inline-flex items-center justify-center gap-2 rounded-md font-medium',
    'transition-colors disabled:pointer-events-none disabled:opacity-50',
    BUTTON_VARIANTS[variant],
    BUTTON_SIZES[size],
    className,
  )
}
