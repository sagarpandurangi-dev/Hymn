# Universal Dream Engine architecture

## Purpose

The Dream Engine is Hymn's shared control plane for “I want to…”, Learning,
Goal planning, and Project planning. A proposal is a reviewable draft. It cannot
create Goals, Projects, Outcomes, Tasks, phases, or check-in requirements until
the authenticated owner explicitly applies a reviewed revision.

The local v1 is deterministic. It is intentionally useful when offline and is
also the authoritative safety fallback for future AI or research providers.

## Provider boundaries

Three provider-neutral contracts live in `backend/dream_providers.py`:

1. `IntentInterpretationProvider` turns free-form text into typed candidate
   interpretations, alternatives, extracted facts, and uncertainties.
2. `ResearchProvider` answers approved public-information questions with
   evidence containing a URL, page title, publisher, retrieval time, and
   effective/expiry dates where relevant.
3. `PlanSynthesisProvider` receives a confirmed interpretation, a deliberately
   minimized owned-context summary, and user-approved research evidence. It may
   suggest a plan tree.

Provider output is untrusted suggestion data. Pydantic rejects unexpected
fields, and the deterministic Dream verifier rejects invalid hierarchy,
duplicate IDs, cycles, stale revisions, unsupported check-in definitions,
ownership violations, invalid dates/currencies, and unsafe apply actions.
Providers have no database handle and cannot persist or apply records.

No provider is configured in v1. Research states include
`research_recommended`, `research_in_progress`, `research_ready`,
`research_stale`, `research_failed`, and `manual_input_required`. Provider
failure always leaves manual/custom planning available.

## Privacy boundary

Raw profile, account, health, check-in, and portfolio rows stay inside Hymn by
default. A future provider may receive only the minimum structured facts or
derived summaries that the user and deployment configuration explicitly allow.
Finance and health context need separate consent gates. Public research must
never receive raw balances merely because Hymn uses them locally to assess
personal burden.

External factual claims require source evidence. Search-result snippets are not
evidence. Prefer official or primary publishers, record freshness, and mark
stale evidence before replanning.

## Evidence categories

Every conclusion can refer to one or more typed evidence items:

- user facts
- Hymn-owned context
- deterministic calculations
- AI inference
- web-sourced facts
- assumptions
- missing data

Only plain-language summaries appear on the main review surface. Technical
provenance is available under “Why does Hymn think this?”

## Canonical plan mapping

The accepted plan map is the stable source of hierarchy and revision history:

`Plan → Phase (optional) → Milestone/Expected Outcome → Task → Required Check-in`

- `active_plan_maps` stores the accepted, versioned tree and source attachment.
- `plan_phases` stores accepted phase records where phases are useful.
- Goal/Learning milestones map to the existing `expected_outcomes` model.
- Project or free-dream milestones remain canonical nodes in the accepted map;
  they are not forced into an unrelated Goal.
- Tasks map to the existing `tasks` model and retain their plan node ID.
- `required_checkin_requirements` describes future requested evidence. It never
  creates a fake `checkins` response.
- Actual user updates continue to use the existing `checkins` collection.

Display numbering is derived from tree position. Stable UUIDs—not “Phase 2” or
“1.1”—are identities, so insertion, reordering, deletion, and subtree moves do
not break links.

## Apply safety

Apply is keyed by proposal ID, proposal revision, and stable node ID. A
per-action log makes retries idempotent. A preparing/applying/committed state
machine and compensating cleanup protect local single-node MongoDB, where
multi-document transactions are unavailable. Replanning creates a new proposal
revision and does not mutate the accepted map or user-authored nodes silently.

## Future examples

### CA qualification

A future interpretation provider can recognize the qualification. Research may
be recommended for current rules and must use official ICAI sources wherever
possible. Hymn can then combine cited requirements with locally computed
time/money capacity and the user's confirmed current progress. If research is
unavailable, the user can enter the official phases manually and still build a
complete plan.

### Ferrari purchase

A future interpretation provider can ask which model and location the user
means. Approved public research may provide cited, dated price ranges. Hymn's
deterministic finance verifier then compares a confirmed price/currency with
compatible recorded resources locally. Raw account rows do not need to leave
the device/provider boundary.

## Work required before enabling AI or web research

- choose providers and deployment/data-processing regions;
- approve keys, retention terms, privacy disclosures, and per-domain consent;
- implement provider adapters, rate limits, redaction, and observability;
- define authoritative-source policies and evidence freshness by journey type;
- add adversarial schema/prompt-injection tests and provider evaluation sets;
- add a user-visible research approval and source-review experience.

None of those decisions is made by this v1.
