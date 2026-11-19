import { Pressable, Text, View } from "react-native";
import { formStyles as s } from "@/src/lib/formStyles";
import { spacing } from "@/src/lib/theme";

const OPTIONS: { label: string; minutes: number }[] = [
  { label: "15m", minutes: 15 },
  { label: "30m", minutes: 30 },
  { label: "45m", minutes: 45 },
  { label: "60m", minutes: 60 },
  { label: "2h", minutes: 120 },
  { label: "3h", minutes: 180 },
];

export const DURATION_REQUIRED = "How long did it take?";

/** "· 45m" / "· 2h" suffix for check-in lists; empty when no duration. */
export function durationSuffix(minutes?: number | null): string {
  const m = Number(minutes);
  if (!m || !Number.isFinite(m)) return "";
  return ` · ${m >= 120 && m % 60 === 0 ? `${m / 60}h` : `${m}m`}`;
}

/** Required "how long" row: tap one to select it; tapping another replaces it. */
export default function DurationPicker({ value, onChange, testID }: { value: number | null; onChange: (m: number) => void; testID: string }) {
  return (
    <>
      <Text style={s.label}>How long did it take?</Text>
      <View style={{ flexDirection: "row", gap: spacing.xs }} testID={testID}>
        {OPTIONS.map((o) => {
          const sel = value === o.minutes;
          return (
            <Pressable
              key={o.minutes}
              onPress={() => onChange(o.minutes)}
              style={[s.chip, { flex: 1, minWidth: 0, minHeight: 44, paddingHorizontal: 0 }, sel && s.chipSelected]}
              accessibilityRole="radio"
              accessibilityState={{ selected: sel, checked: sel }}
              aria-checked={sel}
              testID={`${testID}-${o.minutes}`}
            >
              <Text style={[s.chipText, sel && s.chipTextSelected]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </>
  );
}
