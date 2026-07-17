# Repo Surgeon Dashboard — UI/UX Overhaul Plan

Design direction, motion system, screen-by-screen redesign, and implementation phases.
Nothing in the running app has been changed; the prototype files listed at the bottom are
new, unimported, typecheck- and lint-clean, and ready to wire in.

---

## 1. Audit of the current UI

What works (keep):

- Solid information architecture — submit → job detail with stepper, scout report, plan,
  item cards, PRs, event log is the right hierarchy. The redesign restyles it, not restructures it.
- Live SSE updates, skeleton loaders, empty states, reconnecting indicator all exist.
- Responsive stepper (vertical on mobile) is already handled.

What's weak:

- **No identity.** Neutral-900 panels + default Tailwind blue = any admin template. Nothing
  says "autonomous surgeon operating on your codebase."
- **Actual bug:** `globals.css` sets `font-family: Arial` on `body`, overriding the Geist
  fonts that `layout.tsx` loads. The whole app renders in Arial today.
- **No motion system.** The only animations are `animate-pulse`. Panels pop in with no
  entrance; state changes (the most exciting thing in a live pipeline) don't animate.
- Buttons/inputs have minimal affordance (no press states, weak focus treatment).
- Four different accents (blue action, blue category, blue risk bar, blue links) with no
  hierarchy between "brand" and "semantic."
- Home page is a form floating in a void — no hero moment for a demo-day product.

## 2. Design direction — "The Operating Theater"

Repo Surgeon performs surgery on codebases. The identity borrows from the operating room:

- **Ground:** lights-off theater. Cold, blue-biased near-blacks — never pure grey.
- **Accent:** **scrub teal** `#2de0bf`. Surgical scrubs are teal because it's the optical
  complement of blood red; here red is reserved *exclusively* for failure ("bleeding").
  One accent, spent deliberately. Blue disappears as a brand color.
- **Voice:** Geist Mono is the "instrument readout" — job ids, versions, event log,
  uppercase section eyebrows (`SCOUT REPORT`, `OPERATIONS`). Geist Sans carries UI copy.
- **Motion:** calm and precise, like steady hands. Nothing bounces; things settle.
- **Signature effect:** a magnetic field of fine lines on the home hero that orient toward
  the cursor — iron filings around a magnet, the surgeon's instruments aligning to your hand.

### Palette (defined in `src/styles/theme.css`)

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#06080c` | Page ground |
| `--surface-1` / `--surface-2` | `#0b0f16` / `#111826` | Panels / nested surfaces |
| `--border` / `--border-strong` | `#1a2231` / `#263145` | Hairlines / hover |
| `--text` / `--text-muted` / `--text-faint` | `#e8edf5` / `#96a0b5` / `#5b6478` | Ink hierarchy |
| `--accent` / `--accent-bright` | `#2de0bf` / `#8cf5e0` | Brand actions, live states, links |
| `--ok` / `--warn` / `--danger` / `--info` | `#4ade80` / `#fbbf24` / `#ff6b6b` / `#6aa6ff` | Semantic only |

Semantic mapping change: **running = accent teal** (the machine is alive), **green = merged
/ verified only**, amber = needs_human, red = failed. Today "running" and "links" and
"minor upgrades" are all the same blue.

### Typography

- Fix the Arial bug: `body { font-family: var(--font-geist-sans), system-ui, sans-serif }`.
- Scale: 30/20/14/12/11 with `tracking-tight` on headings and `text-wrap: balance`.
- All-caps mono eyebrows (`.eyebrow` utility) replace the current uppercase-sans section labels.
- `tabular-nums` on every numeric readout (stats, log timestamps, versions).

## 3. Screen-by-screen redesign

### Layout shell (`layout.tsx`)

- Slim sticky top bar: 🩺 wordmark `REPO SURGEON` in mono, right side shows backend
  connection dot (`.dot-live`). Glass background (`--surface-glass` + `backdrop-blur`).
- Page content fades up on route change (`.rise-in` on `main`).

### Home (`app/page.tsx`)

The command deck. This is the demo-day money shot.

1. **Hero** (~60vh): `MagneticField` canvas behind, radial vignette so lines fade toward
   edges. Headline set large/tight ("Operates on your repo. Unattended."), one-line
   subhead, then the **command input**:
   - Oversized (h-14), mono placeholder cycling through example repo URLs (typewriter, ~4s
     cycle, pauses on focus; skipped under reduced motion).
   - Focus state: border shifts to accent + `--glow-accent` ring. This is the one glowing
     element on the page.
   - Button label stays "Operate"; on submit it swaps to a scalpel-line loading shimmer.
   - Validation error slides down (`rise` keyframe), input border flashes `--danger`.
2. **Recent operations**: `GlowCard` rows with staggered entrance (`.rise-in` +
   `staggerDelay(i)`), each showing repo name (large) over full URL (faint mono), job id
   with click-to-copy, relative time, and the redesigned `StateBadge`. Hover: 2px lift +
   border light tracking the cursor (built into `GlowCard`).
3. Empty state: small static magnetic-field motif + "No operations yet — point the surgeon
   at a repository."

### Job page (`app/jobs/[id]/page.tsx`)

The operating room monitor.

- **Sticky vitals header**: repo name + copyable job id, elapsed time ticking live in mono,
  `StateBadge`, reconnecting chip. Compresses on scroll (padding/font-size transition).
- **Pipeline rail** (`PipelineStepper` redesign):
  - Nodes become status-shaped, not just colored: pending = hollow ring, active = filled
    accent with `pulse-ring`, complete = check drawn in with an SVG `stroke-dashoffset`
    transition (~300ms), failed = red ×, needs_human = amber flag.
  - Connectors: completed = solid accent; **active = `.connector-active` shimmer** (light
    flowing left→right toward the current stage — reads as "work is flowing").
  - Stage label of the active node in accent; sub-caption under it (e.g. "attempt 3/5 on
    fastapi") pulled from the latest event.
- **Scout report** (`ScoutSummary`): stat tiles with `AnimatedNumber` count-up on reveal;
  vulnerability chips get severity-colored left stripe; build status becomes ✓/✗ icon + word.
- **Upgrade plan** (`PlanTable`): rows stagger in; risk bar animates from 0 to value on
  reveal and is colored by band (teal <40, amber <70, red ≥70) instead of always blue;
  category chips keep semantic colors but security gets a subtle red stripe. Row hover
  highlights; rationale expands on click instead of `title`-attr truncation.
- **Item cards** (`ItemCard` on `GlowCard`):
  - Attempt dots grow to 3.5px and get states: upcoming = hollow, running = accent pulse,
    pass = green fill (pop-in scale), fail = red fill. Connect with a hairline so it reads
    as the retry loop it is.
  - Scores use `AnimatedNumber`; grade word colored via existing `quality.ts`.
  - Status line for in-progress items gets a live dot; card border tints by outcome
    (teal running / green / amber / red at ~25% alpha).
  - New iteration event triggers a one-shot border flash (accent → rest, 600ms).
- **Diff viewer**: slide-open (grid-template-rows 0fr→1fr); file chips clickable to jump;
  line numbers in gutter; copy-patch button; keep existing +/- coloring but on `--surface-2`.
- **Event log**: full terminal treatment — mono, `--bg` ground, faint scanline texture
  (2px repeating-linear-gradient at 3% alpha), new lines slide in from bottom, blinking
  block cursor on the last line while connected (`blink` keyframe), auto-scroll pauses
  when the user scrolls up (show "↓ 12 new" chip), stage names colored by stage.
- **PR panel**: link cards instead of bare URLs — repo/branch title, covered items count,
  mock badge, arrow-slides-right hover.
- **StateBadge**: pill with a leading status dot; running = teal dot with `pulse-ring`
  (replaces whole-badge `animate-pulse`, which reads as "broken" rather than "alive").
- **Terminal states**: on `done`, a single one-shot moment — the rail's final node draws
  its check and a brief radial teal wash sweeps the header (no confetti; this is surgery).
  `needs_human` gets an amber banner explaining *what* needs a human, with the flagged
  items linked.

## 4. Motion system

Single source of truth: CSS vars in `theme.css`, JS mirrors in `src/lib/motion.ts`.

| Token | Value | Use |
| --- | --- | --- |
| `--ease-out` | `cubic-bezier(0.22, 1, 0.36, 1)` | Everything by default |
| `--ease-spring` | `cubic-bezier(0.34, 1.4, 0.64, 1)` | Small pop-ins only (dots, chips) |
| `--dur-fast` 150ms | hover, press | |
| `--dur-base` 240ms | color/border/lift transitions | |
| `--dur-slow` 420ms | expand/collapse, layout shifts | |
| `--dur-entrance` 600ms | page/panel entrances, counters | |

Rules:

1. Entrances animate opacity + ≤14px translate only; never scale whole panels.
2. Stagger 60ms/child, capped at 480ms (`staggerDelay`).
3. State changes always animate (they're the product); decorative motion must be ambient
   and interruption-free.
4. Everything respects `prefers-reduced-motion` — entrances/shimmer/canvas off, counters
   render final values (already handled in the prototypes and `theme.css`).
5. No new dependencies. CSS + rAF cover all of the above; revisit `motion` (framer) only
   if we later want shared-layout transitions between list and detail.

## 5. Signature effect — MagneticField

`src/components/fx/MagneticField.tsx` (built, working):

- A grid of short lines on one `<canvas>`; each line eases its rotation toward the cursor
  within a 220px influence radius (smoothstep falloff), lengthening ~2× and blending from
  cold grey-blue toward scrub teal as the cursor nears. Outside the radius, lines drift
  slowly on per-point phase offsets so the field looks alive but calm.
- Angle easing is asymmetric: excited lines snap (0.25), resting lines glide (0.05) — this
  is what makes it feel magnetic rather than merely tracking.
- Performance: single rAF, no DOM per line, DPR capped at 2, point count capped at ~4.2k
  (pitch auto-widens on huge viewports), pauses via `visibilitychange` + IntersectionObserver.
- Reduced motion: renders one static frame, no loop, no pointer listener.
- Usage: absolutely-positioned behind the home hero with a radial-gradient vignette overlay;
  optionally a low-alpha strip (`restAlpha≈0.15`, no pointer chase) behind the job header.

## 6. Accessibility & performance checklist

- [ ] Focus-visible ring (accent, 2px offset) on every interactive element.
- [ ] `aria-live="polite"` on StateBadge + stepper region so state changes are announced.
- [ ] Event log: `role="log"`, and the auto-scroll pause doubles as a screen-reader courtesy.
- [ ] Contrast: `--text-muted` on `--surface-1` ≥ 4.5:1 (verified); accent used at 14px+ only.
- [ ] Canvas is `aria-hidden` and pointer-events-none (decorative).
- [ ] Keep the bundle honest: zero new runtime deps in this overhaul.
- [ ] Lighthouse pass after Phase 2 (hero canvas) — target no main-thread task >50ms.

## 7. Implementation phases

| Phase | Scope | Est. |
| --- | --- | --- |
| **1. Foundations** | Import `theme.css`, fix Arial bug, retint existing components to tokens (mechanical class swap), nav shell, focus states | ~half day |
| **2. Home** | Hero + `MagneticField`, command input, typewriter placeholder, recent-jobs `GlowCard` list | ~half day |
| **3. Job page** | Stepper rail, StateBadge, ScoutSummary + `AnimatedNumber`, PlanTable | ~1 day |
| **4. Live-feel** | ItemCard attempt loop, diff slide-open, terminal event log, PR cards, terminal-state moments | ~1 day |
| **5. Polish** | A11y/contrast/reduced-motion sweep, perf check, mobile pass | ~half day |

Each phase ships independently — Phase 1 alone already changes the perceived quality.

## 8. Prototype files already built (unimported — zero effect until wired in)

| File | What it is |
| --- | --- |
| `src/styles/theme.css` | Full token system, keyframes (`rise`, `shimmer`, `pulse-ring`, `blink`), utilities (`.eyebrow`, `.panel`, `.rise-in`, `.connector-active`, `.dot-live`), reduced-motion guards |
| `src/components/fx/MagneticField.tsx` | The magnetic-lines canvas (spec above), fully self-contained |
| `src/lib/motion.ts` | JS motion tokens, `easeOutExpo`, `staggerDelay`, `useReducedMotion` |
| `src/components/ui/GlowCard.tsx` | Cursor-tracked border-light panel (masked gradient ring) |
| `src/components/ui/AnimatedNumber.tsx` | In-view count-up stat, tabular-nums, reduced-motion safe |

Wiring on adoption: add `@import "../styles/theme.css";` to `globals.css`, replace the old
`:root` block, and set the body font to the Geist variable. All prototypes pass
`tsc --noEmit` and `eslint` against the current config.
