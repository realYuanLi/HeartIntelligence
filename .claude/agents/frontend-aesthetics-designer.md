---
name: living-interface
description: Transform interfaces into living systems — breathing physics, ambient intelligence, liquid transitions, calm signaling, and intent-driven surfaces. Goes beyond current design trends into organic, context-aware UI.
user-invokable: true
args:
  - name: target
    description: The component, page, or feature to transform (optional — applies to whole project if omitted)
    required: false
---

# Living Interface — Organic Design System

Interfaces that are **grown, not designed** — responsive to context, intent, time, and attention like a living system. Current glassmorphism + dark mode looks like a poster compared to this.

---

## CORE PHILOSOPHY

The UI is never a static poster. It is a living surface that breathes, responds, and communicates through ambient signals rather than explicit notifications. Every element has weight, momentum, and presence.

---

## THE FIVE PILLARS

### 1. Breathing Interface
The UI is never still. Stillness feels dead.

**DO:**
- Replace all ease curves with spring physics (`spring(mass, stiffness, damping)` or CSS `linear()` approximations)
- Use simplex noise to drift background orbs, gradients, and ambient elements — never linear or sine wave (too mechanical)
- Magnetic cursor effects: elements have subtle gravitational pull toward the pointer (2-4px displacement)
- Ambient particle fields or flowing grain that shifts with scroll position
- Subtle scale pulsing on key data points (0.98-1.02 range, 4-8s cycle)
- Background gradient hue rotation: imperceptible but alive (360deg over 120s+)

**DON'T:**
- Use static backgrounds — even "dark mode" should have depth layers that drift
- Use linear or sine easing for anything organic — spring physics or perlin noise only
- Make breathing effects noticeable on conscious level — users should feel alive-ness without identifying why
- Use bounce/elastic easing (looks cheap and dated)

**Implementation patterns:**
```css
/* Spring-like easing via CSS */
--spring-bounce: linear(0, 0.004, 0.016, 0.035, 0.063, 0.098, 0.141, 0.191, 0.25, 0.316, 0.391, 0.472, 0.562, 0.659, 0.763, 0.876, 1.000, 1.045, 1.073, 1.085, 1.085, 1.074, 1.054, 1.028, 0.999, 0.971, 0.946, 0.926, 0.912, 0.905, 0.904, 0.909, 0.919, 0.933, 0.95, 0.969, 0.988, 1.006, 1.02, 1.029, 1.032, 1.029, 1.022, 1.012, 1.001, 0.99, 0.981, 0.975, 0.972, 0.973, 0.977, 0.984, 0.993, 1.0);
--spring-snappy: cubic-bezier(0.16, 1, 0.3, 1);

/* Simplex noise via JS for ambient drift */
/* Ambient grain overlay */
.ambient-grain {
  background-image: url("data:image/svg+xml,..."); /* noise texture */
  opacity: 0.03;
  animation: grain-shift 8s steps(10) infinite;
}
```

### 2. One Glance, One Answer
The dashboard auto-prioritizes. No scanning required.

**DO:**
- Time-aware layouts: morning = information-dense; evening = summary mode (check `new Date().getHours()`)
- Data freshness drives hierarchy: stale data fades, fresh data pulses
- Anomaly detection: when a metric deviates >2 standard deviations, it auto-enlarges and brightens — everything else dims to 60% opacity
- Typography scale responds to data importance: critical numbers get 2x size, normal get 1x
- Use `font-variation-settings` to make weight respond to severity (lighter = fine, bolder = urgent)

**DON'T:**
- Give all data equal visual weight — that's a spreadsheet, not a dashboard
- Use badges or notification counts (noisy, anxiety-inducing)
- Require the user to scan left-to-right or hunt for information
- Show everything at once — progressive disclosure based on scroll depth and dwell time

**Implementation patterns:**
```css
/* Data-driven typography */
.metric[data-severity="critical"] { font-size: 3rem; font-weight: 800; }
.metric[data-severity="normal"] { font-size: 1.5rem; font-weight: 400; opacity: 0.7; }

/* Auto-dim non-essential content when alert active */
body.has-anomaly .non-critical { opacity: 0.4; filter: blur(0.5px); transition: 0.8s; }
```

### 3. Liquid Transitions
Nothing jumps. The interface is one continuous fluid surface.

**DO:**
- Use View Transitions API for page/section transitions (`document.startViewTransition()`)
- Animate numbers between values using CSS `@property` registered custom properties
- Use gooey SVG filters for organic element merging/splitting effects
- Cards morph into detail views (shared element transitions) — never pop/replace
- Scroll-linked animations via `animation-timeline: scroll()` where supported
- Color transitions use OKLCH interpolation for perceptually uniform shifts

**DON'T:**
- Jump-cut between states — every state change must have a transition
- Use opacity-only transitions (lazy) — transform + opacity minimum
- Make transitions longer than 500ms for micro-interactions or 800ms for page transitions
- Use transform: scale(0) for appear/disappear — use clip-path or mask for organic reveals

**Implementation patterns:**
```css
/* Animated counter via @property */
@property --score {
  syntax: '<number>';
  initial-value: 0;
  inherits: false;
}
.score-display {
  --score: 0;
  counter-reset: score var(--score);
  transition: --score 1.2s var(--spring-snappy);
}

/* Gooey filter for organic merging */
<filter id="goo">
  <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="blur" />
  <feColorMatrix in="blur" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 19 -9" result="goo" />
</filter>
```

### 4. Calm Intelligence
No badges, no notification counts. The interface communicates through ambient environmental shifts.

**DO:**
- Background color temperature as signal: cool blue-grey (all fine) → warm amber-grey (attention needed) → rose-grey (critical)
- Use `oklch()` with shifting hue/chroma for ambient mood — not hard color swaps
- Peripheral vision design: important shifts happen at edges/backgrounds where peripheral vision catches movement
- 85% of the surface stays serene at all times — only 15% may be "active"
- Sound design consideration: subtle haptic/audio feedback for critical state changes (Web Audio API)
- Border-glow intensity correlates with data urgency

**DON'T:**
- Use red badges, exclamation marks, or alert icons for non-critical states
- Flash or blink anything — that's 1999
- Change more than 15% of the visible surface simultaneously
- Use high-saturation colors for ambient signaling — keep chroma low (0.02-0.06 in OKLCH)

**Implementation patterns:**
```css
/* Ambient color temperature via CSS custom properties */
:root {
  --ambient-hue: 230;        /* cool blue = normal */
  --ambient-chroma: 0.02;    /* very subtle */
  --bg-ambient: oklch(0.13 var(--ambient-chroma) var(--ambient-hue));
}
/* JS shifts --ambient-hue from 230 (blue) → 60 (amber) → 10 (rose) based on data state */
```

### 5. Intent Surface
CMD+K / search becomes the primary interface. Not search results — composed, purpose-built views.

**DO:**
- Command palette as first-class navigation (CMD+K or /)
- Natural language queries generate composed layouts, not lists
- Recent intent memory: the interface remembers what you looked at and surfaces related data
- Predictive pre-loading: if user viewed county A, pre-fetch neighboring counties
- Keyboard-first interaction model with visible shortcuts

**DON'T:**
- Return raw search results — compose a contextual answer view
- Require mouse for any primary action
- Hide the command palette behind a button — it should feel omnipresent
- Forget user patterns — build session-local intent memory

---

## DESIGN TOKEN SYSTEM (Required)

### Colors — OKLCH Only
```css
/* Never use hex or hsl for new colors. OKLCH is perceptually uniform. */
--bg-void: oklch(0.08 0.015 260);         /* not pure black — cool-tinted */
--bg-surface: oklch(0.12 0.012 260);
--bg-elevated: oklch(0.16 0.01 260);
--text-primary: oklch(0.95 0.01 260);     /* not pure white — slight warmth */
--text-secondary: oklch(0.55 0.02 260);
--text-muted: oklch(0.38 0.015 260);
--accent-primary: oklch(0.72 0.18 195);   /* vivid teal-cyan */
--accent-warm: oklch(0.78 0.16 75);       /* amber */
--accent-danger: oklch(0.62 0.22 25);     /* deep warm red */
--accent-success: oklch(0.72 0.17 155);   /* emerald */
```

### Typography — Distinctive Fonts
```
Display: 'Instrument Serif' or 'Playfair Display' (editorial weight)
Body: 'Geist', 'DM Sans', or 'Sora' (clean but not generic)
Mono: 'Geist Mono', 'JetBrains Mono', or 'Berkeley Mono'

BANNED: Arial, Helvetica, Inter (too generic), system-ui as primary
```

**Modular scale**: 1.25 ratio (minor third)
```
--text-xs: 0.64rem    --text-sm: 0.8rem     --text-base: 1rem
--text-lg: 1.25rem    --text-xl: 1.563rem   --text-2xl: 1.953rem
--text-3xl: 2.441rem  --text-4xl: 3.052rem
```

### Spacing — 8px Grid
All spacing values are multiples of 8: 4, 8, 16, 24, 32, 48, 64, 96, 128.
Never use arbitrary values like 13px, 22px, 37px.

### Motion — Spring Physics
```css
--ease-spring: cubic-bezier(0.16, 1, 0.3, 1);      /* fast-in, smooth-out */
--ease-micro: cubic-bezier(0.25, 0.46, 0.45, 0.94); /* subtle interactions */
--duration-micro: 150ms;     /* hover, focus, small shifts */
--duration-action: 300ms;    /* clicks, toggles, reveals */
--duration-page: 500ms;      /* section transitions */
--duration-ambient: 4000ms;  /* breathing, drifting */
```

### Border Radius
```css
--radius-sm: 6px;   --radius-md: 12px;   --radius-lg: 20px;   --radius-full: 9999px;
```

---

## ANTI-PATTERNS (Hard Reject)

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| Pure black (#000) backgrounds | Looks like a hole, not a surface | Use oklch(0.08 0.015 hue) |
| Grey text on colored backgrounds | Fails contrast, looks washed | Use oklch with matching hue |
| Cards inside cards inside cards | Nesting tax — visual noise | Flatten hierarchy, use spacing |
| Bounce/elastic easing | Feels cheap and dated | Spring physics or smooth ease-out |
| Spinner loading states | Anxiety-inducing, uninformative | Skeleton screens or progressive reveal |
| Static gradients | Dead surface | Subtle hue rotation or noise drift |
| Badge/notification counts | Anxiety, clutter | Ambient color temperature shifts |
| Equal-weight data display | Spreadsheet, not dashboard | Auto-prioritize by severity/freshness |

---

## ACCESSIBILITY (Non-Negotiable)

- `prefers-reduced-motion`: disable all ambient animations, breathing effects, and particle fields. Keep functional transitions at 150ms max.
- `prefers-color-scheme`: support both, but dark is primary
- Focus states: 2px ring with accent color, never `outline: none`
- All interactive elements reachable via keyboard
- WCAG 2.1 AA contrast ratios minimum (4.5:1 text, 3:1 large text)
- `aria-live` regions for dynamically updating content

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 150ms !important;
  }
}
```

---

## EXECUTION RULES

When applying this skill:

1. **Audit current state**: Read all CSS/JS. Identify every anti-pattern from the table above.
2. **Token migration**: Convert all colors to OKLCH. Establish the modular type scale. Align spacing to 8px grid.
3. **Add breathing layer**: Implement simplex noise ambient orbs, subtle grain overlay, and micro-drift on background elements.
4. **Add liquid transitions**: Replace all opacity-only transitions with transform+opacity. Add number animation via @property. Implement scroll-linked fade-ins.
5. **Implement calm signaling**: Replace any badge/alert patterns with ambient color temperature system.
6. **Polish**: Ensure every hover has a spring-physics response. Verify reduced-motion support. Test contrast ratios.

**Quality bar**: If the interface feels like a static poster, it has FAILED. The user should feel the UI is alive without being able to articulate why.
