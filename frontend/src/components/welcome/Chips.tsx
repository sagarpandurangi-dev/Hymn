import { Pressable, Text, View } from "react-native";

import { formStyles as s } from "@/src/lib/formStyles";
import { spacing } from "@/src/lib/theme";

type Option = { value: string; label: string };

/** Wrapping row of tappable chips. `selected` is the list of selected values. */
export default function Chips({ options, selected, onToggle, testID }: { options: Option[]; selected: string[]; onToggle: (v: string) => void; testID: string }) {
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }} testID={testID}>
      {options.map((o) => {
        const on = selected.includes(o.value);
        return (
          <Pressable
            key={o.value}
            onPress={() => onToggle(o.value)}
            style={[s.chip, { minHeight: 44 }, on && s.chipSelected]}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            testID={`${testID}-${o.value}`}
          >
            <Text style={[s.chipText, on && s.chipTextSelected]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
