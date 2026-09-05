/**
 * A proportion as a Tailwind width class.
 *
 * Tailwind emits a class only if it literally appears in the source, so an
 * arbitrary computed width cannot become one — and `style={{ width }}` is
 * forbidden (CONVENTIONS-CLIENT.md §11). The compromise is twenty-one literal
 * classes and a value quantised to 5% steps, which is ample for a bar somebody
 * reads at a glance; the number printed beside it always carries the exact
 * figure.
 *
 * Kept out of `ProgressBar.tsx` so that file exports only a component.
 */
/** Literal, because Tailwind must see each one in the source to emit it. */
const WIDTH_CLASS: readonly string[] = [
  'w-0',
  'w-[5%]',
  'w-[10%]',
  'w-[15%]',
  'w-[20%]',
  'w-[25%]',
  'w-[30%]',
  'w-[35%]',
  'w-[40%]',
  'w-[45%]',
  'w-[50%]',
  'w-[55%]',
  'w-[60%]',
  'w-[65%]',
  'w-[70%]',
  'w-[75%]',
  'w-[80%]',
  'w-[85%]',
  'w-[90%]',
  'w-[95%]',
  'w-full',
]

/** 0…1 to one of the twenty-one steps, clamped at both ends. */
export function widthClass(fraction: number): string {
  if (!Number.isFinite(fraction)) return WIDTH_CLASS[0] as string
  const step = Math.round(Math.max(0, Math.min(1, fraction)) * 20)
  return WIDTH_CLASS[step] ?? (WIDTH_CLASS[0] as string)
}

