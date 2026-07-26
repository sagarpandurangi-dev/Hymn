export const normalizeDisplayName = (value: string): string =>
  value.trim().replace(/\s+/g, " ");

export const displayNameValidationError = (value: string): string | null => {
  const normalized = normalizeDisplayName(value);
  if (!normalized) return "Enter your name.";
  if (normalized.length > 80) return "Name must be 80 characters or fewer.";
  return null;
};

export const displayNameInitials = (
  displayName: string | null | undefined,
): string | null => {
  const normalized = normalizeDisplayName(displayName || "");
  if (!normalized) return null;
  const parts = normalized.split(" ");
  const selected = parts.length === 1 ? parts : [parts[0], parts[parts.length - 1]];
  return selected
    .map((part) => Array.from(part)[0])
    .join("")
    .toLocaleUpperCase();
};
