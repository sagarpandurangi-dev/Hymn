# Hymn design guide

Owner approved the direction on 21 Nov 2026 ("much, much better"; the old look "looked like an obituary").
Mock-ups: the "Hymn Redesign" artifact (Today, Money, Life, My week, now vs new). The app gets this look from
Emergent prompt **0. Design pass**, run before N–S.

## Feel

Calm, warm, alive. Your day first, never a menu. One thing leads on every screen. It speaks like a friend who
is good with money and time, never like accounting software, and never like an obituary.

## Type

- **Outfit** for headings (closest to the ॥ logo Gemini drew); **Figtree** for everything else.
- Six sizes only: **34** display (one per screen at most), **26** title, **20** heading, **16** body, **14** small,
  **12** caption. Nothing below 12. Body text is 16.
- Section labels: 12, uppercase, letter-spacing 1, soft colour.
- Screen titles are left-aligned, no full stop ("Today", never "Today.").

## Colour

| Token | Hex | Use |
|---|---|---|
| Paper | `#FAF7F1` | background |
| Card | `#FFFFFF` | the few things that stand apart |
| Ink | `#1F2340` | text, the + button, primary buttons |
| Soft | `#6B7180` | secondary text |
| Faint | `#A3A7B0` | done items, hints |
| Line | `#ECE6DB` | dividers |
| Saffron | `#E0812A` | the ॥ and at most one highlight per screen |
| Saffron soft | `#FBEBDB` | the highlight card (a birthday, a payment due) |
| Sage | `#5E7B63` / soft `#E4ECE3` | done, good, money coming in |
| Warning | `#C9822B` · Error `#B5483B` | only for real problems |

## Layout

- The most important thing on each screen leads and is the biggest.
- **Cards only for what stands apart** (a birthday, free money, free time). Lists are plain rows with hairline
  dividers on paper, not a grey box per section.
- Spacing scale 4, 8, 12, 16, 24, 32; 20 at the sides. Card radius 18, buttons 14, pills fully round.
- Empty is an invitation ("Add your first bill"), never a table of zeros. Hide rows whose value is zero.

## Words and numbers

- Money: **₹12,450**, **₹1.84 L**, **₹2.5 Cr**; no ".00"; no "INR" before rupee amounts; other currencies keep
  their code ("USD 1,250"). Incoming money "+ ₹1.1 L" in sage.
- Days: **Today, Tomorrow, Yesterday**, a weekday within the coming week ("Tuesday"), else "24 Nov" (year only
  when it isn't this year). Never 2026-11-24.
- Durations: "45 min", "3h", "3h 20m".
- Plain words: "Left to spend" (not "available unreserved"), "Ready to use / Takes a few days / Long-term" (not
  liquid / semi-liquid / illiquid), "Comes in / goes out every month" (not recurring income / expenses),
  "Check-ins due" (not "Required check-ins").
- The server already words things this way: `backend/display.py` (money, day, duration, greeting), used by the
  screen answers below. The app's `src/lib/format.ts` follows the same rules.

## Screen answers (server, one call per screen)

| Route | What it gives |
|---|---|
| `GET /api/screens/today` | `date_label`, `greeting`; `things` (up to 3: one done today, then overdue first, then due today; each `task_id, title, done, note` e.g. "since Tuesday"), `more_things`; `highlight` (next birthday/occasion within 7 days, else a payment due within 7 days: `kind, title, when, detail, screen`) or null; `free_time` {minutes, label, when: "today" / "this evening"}; `money` {amount, currency, label} (left to spend); `review` {open} or null; `setup` {done, of, next {title, screen}} or null when complete |
| `GET /api/screens/life` | `areas`: health, family, learning, work, plans — each `key, title, screen, line, status` (good · attention · setup · quiet) |
| `GET /api/screens/finance` | as before, plus `headline` {currency, net_worth, net_worth_label, left_to_spend, left_to_spend_label, coming_up [{id, title, direction, when, amount_label}]} |

Every part is optional: a part with nothing to say is null, never zeros.
