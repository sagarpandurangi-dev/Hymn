# Hymn beta: tester plan

## Who and how many
- **10–15 people you know**, mixed on purpose: salaried and self-employed, with and without a smartwatch, at least two who track money carefully and two who never have, one student (for Learning), one person looking after a parent (for caregiver mode).
- Android first (that's the published build).
- Tell them plainly: it's a beta, things will break, their data is private to them, and they can delete everything from the app.

## What to give each tester
1. The app link and a one-line promise: *"Hymn helps you follow through on your life."*
2. Premium switched on (add their email to `HYMN_PREMIUM_EMAILS` in Railway), so they can test statements, payslips and investments.
3. One place to report: a WhatsApp group or a form. For every problem: **what you did, what you expected, what happened, a screenshot.**

## Day 1 (about 20 minutes)
| Do this | We're checking |
|---|---|
| Sign up; set time zone | Sign-up works; reminders will be on time |
| Follow the setup checklist: bank account, work hours and sleep, 3 people who matter | First-time setup makes sense without help |
| Brain dump: type everything on your mind | Sorting into tasks, reminders, ideas feels right |
| Ask the planner for one small thing ("45 minutes of guitar this week") and one big thing | It finds real free time; the big plan is honest about money |
| Allow notifications | A reminder arrives |

## Days 2–7 (5 minutes a day)
| Do this | We're checking |
|---|---|
| Open the morning reminders; do the 2-minute evening review | Reminders are timely, not annoying |
| Log what you spend, or upload one bank statement and confirm the lines | Suggestions are right; nothing counted twice |
| Check in on tasks, with how long they took | Time tracking is quick |
| If you opted into Health: the 30-second daily log, one food photo | Easy; nothing preachy or scary |
| Log one moment with someone (a call, a meal) | "Might like to hear from you" feels kind |
| Once: tap "stayed late" at work | The week summary reflects it |

## Week 2
| Do this | We're checking |
|---|---|
| Look at the three money statements and the weekly time statement | The numbers match what you know to be true |
| Start a learning journey (an exam, driving, a language) and do 3 days of sessions | Questions make sense; the plan fits; revisions come back |
| Upload a payslip, or an investment statement | Read correctly; totals add up |
| Add a habit to change and use the urge button once | Tone is supportive |
| Try to break it: wrong password 10 times, a huge photo, no internet | It fails politely |
| Download your data; one tester deletes their account | Both work |

## What we measure
- **Setup:** how many finish the checklist on day 1 (target: 8 in 10).
- **Coming back:** how many open it on 5 of the first 7 days (target: half).
- **Trust:** any wrong number in money or time is a top-priority bug.
- **Tone:** any message that felt nagging, scary or guilt-inducing — quote it exactly.
- **Speed:** any screen slower than 3 seconds.

## Bug priorities
1. **Stop everything:** someone sees another person's data; money counted wrong or twice; data lost; can't sign in.
2. **Fix this week:** a feature doesn't work; a reminder at the wrong time; the AI states something false.
3. **Collect:** confusing words, layout, wishes.

## After two weeks
A 15-minute call with each tester: what did you keep using, what did you stop using and why, what would you pay for. Then decide: fix and widen the beta, or change direction on a feature.
