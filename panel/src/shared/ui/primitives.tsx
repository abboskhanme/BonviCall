/**
 * The shared primitives. A component needed in three or more modules lives
 * here (CONVENTIONS-CLIENT.md §1); a module must not grow a parallel Button.
 *
 * Colour comes from the tokens in index.css through the Tailwind names in
 * tailwind.config.js. No hex literal, no `dark:` variant, no inline style.
 */
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'

// The button's look lives beside the button but not inside it, so this file
// keeps exporting components only — see buttonStyles.ts.
import { buttonClasses, type ButtonSize, type ButtonVariant } from './buttonStyles'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
}

export function Button({
  variant = 'primary',
  size = 'md',
  className,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button type={type} className={buttonClasses({ variant, size }, className)} {...props} />
  )
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-xl border border-border bg-surface shadow-soft', className)}
      {...props}
    />
  )
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="status"
      aria-busy="true"
      className={cn('animate-skeleton rounded-md bg-surface-2', className)}
      {...props}
    />
  )
}

type BadgeTone = 'neutral' | 'good' | 'warn' | 'bad' | 'accent'

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: 'bg-surface-2 text-muted',
  good: 'bg-good/10 text-good',
  warn: 'bg-warn/10 text-warn',
  bad: 'bg-bad/10 text-bad',
  accent: 'bg-accent-soft text-accent',
}

export function Badge({
  tone = 'neutral',
  className,
  children,
}: {
  tone?: BadgeTone
  className?: string
  children: ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-sm px-2 py-0.5 text-2xs font-medium',
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'h-10 w-full rounded-md border border-border bg-surface px-3 text-sm text-text',
        'placeholder:text-muted disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

export function Label({
  htmlFor,
  children,
  className,
}: {
  htmlFor: string
  children: ReactNode
  className?: string
}) {
  return (
    <label htmlFor={htmlFor} className={cn('text-xs font-medium text-muted', className)}>
      {children}
    </label>
  )
}
