/**
 * Every colour is a CSS custom property (`hsl(var(--x))`), never a hex literal
 * and never a `dark:` variant: in "system" theme mode there is no
 * `data-theme` attribute at all, so a `dark:` class would silently do nothing
 * for the default case (CONVENTIONS-CLIENT.md §3). The three cases are written
 * out once in src/index.css and nowhere else.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // The `viewer` board is a TV (SPEC §5.2), so the layout has no hard
      // max-width and these breakpoints exist.
      screens: { '3xl': '1920px', '4xl': '2560px' },
      colors: {
        bg: 'hsl(var(--bg))',
        surface: 'hsl(var(--surface))',
        'surface-2': 'hsl(var(--surface-2))',
        border: 'hsl(var(--border))',
        text: 'hsl(var(--text))',
        muted: 'hsl(var(--muted))',
        accent: 'hsl(var(--accent))',
        'accent-fg': 'hsl(var(--accent-fg))',
        'accent-soft': 'hsl(var(--accent-soft))',
        good: 'hsl(var(--good))',
        warn: 'hsl(var(--warn))',
        bad: 'hsl(var(--bad))',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'SF Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.01em' }],
      },
      borderRadius: { sm: '0.5rem', md: '0.75rem', lg: '1rem', xl: '1.25rem', '2xl': '1.5rem' },
      boxShadow: {
        xs: '0 1px 2px hsl(var(--shadow) / 0.04)',
        soft: '0 1px 2px hsl(var(--shadow) / 0.04), 0 2px 8px hsl(var(--shadow) / 0.04)',
        lift: '0 2px 4px hsl(var(--shadow) / 0.04), 0 8px 24px hsl(var(--shadow) / 0.07)',
        pop: '0 4px 8px hsl(var(--shadow) / 0.05), 0 16px 40px hsl(var(--shadow) / 0.1)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        pulse2: { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.45' } },
      },
      animation: {
        'fade-up': 'fade-up 0.3s cubic-bezier(0.32, 0.72, 0, 1) both',
        skeleton: 'pulse2 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
