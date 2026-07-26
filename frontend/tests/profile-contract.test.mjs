import assert from "node:assert/strict";
import test from "node:test";

import {
  displayNameInitials,
  displayNameValidationError,
  normalizeDisplayName,
} from "../src/lib/profile.ts";

test("normalizes a chosen display name without treating email as identity", () => {
  assert.equal(normalizeDisplayName("  Sagar   Pandurangi  "), "Sagar Pandurangi");
  assert.equal(displayNameInitials("Sagar Pandurangi"), "SP");
  assert.equal(displayNameInitials("Sagar"), "S");
  assert.equal(displayNameInitials("Élodie 王"), "É王");
});

test("legacy users without a name have no fabricated initials", () => {
  assert.equal(displayNameInitials(null), null);
  assert.equal(displayNameInitials("   "), null);
  assert.equal(displayNameInitials(undefined), null);
  assert.equal(displayNameValidationError("   "), "Enter your name.");
});

test("validates the public display-name length contract", () => {
  assert.equal(displayNameValidationError("A".repeat(80)), null);
  assert.equal(
    displayNameValidationError("A".repeat(81)),
    "Name must be 80 characters or fewer.",
  );
});
