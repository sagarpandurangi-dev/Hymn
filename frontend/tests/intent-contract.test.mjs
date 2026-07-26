import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildPurchaseUnderstanding } from "../src/lib/intents.ts";

const fixtureUrl = new URL(
  "./fixtures/purchase-slash-date-analysis.json",
  import.meta.url,
);
const analysis = JSON.parse(readFileSync(fixtureUrl, "utf8"));

test("maps an unambiguous slash date from the API into the visible timing fact", () => {
  const understanding = buildPurchaseUnderstanding(analysis);

  assert.ok(understanding);
  assert.deepEqual(
    understanding.facts.map(({ key, value }) => ({ key, value })),
    [
      { key: "intent", value: "Purchase" },
      { key: "item", value: "hero honda splendor" },
      { key: "amount", value: "INR 95,000" },
      { key: "timing", value: "31/12/2026 → 2026-12-31" },
    ],
  );
  assert.equal(
    understanding.facts.find(({ key }) => key === "timing")?.source,
    "Inferred from your sentence",
  );
  assert.equal(understanding.timingResolution, analysis.purchase.timing_resolution);
});
