/**
 * Tap-to-pick month selector (value "YYYY-MM"). Opens an inline year
 * stepper + 12-month grid under the field — no nested modal, so it works
 * inside sheets.
 */
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { financeColors, financeRadius, financeSpace } from "@/src/lib/finance/theme";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const label = (v: string) => {
  const m = /^(\d{4})-(\d{2})$/.exec(v || "");
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : "";
};

type Props = {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  clearable?: boolean;
  testID?: string;
};

export default function MonthPickerField({ value, onChange, placeholder = "Choose month", clearable, testID }: Props) {
  const [open, setOpen] = useState(false);
  const now = new Date();
  const [year, setYear] = useState(() => Number(value?.slice(0, 4)) || now.getFullYear());
  const selected = /^\d{4}-\d{2}$/.test(value || "") ? value : "";

  const toggle = () => {
    if (!open && selected) setYear(Number(selected.slice(0, 4)));
    setOpen((o) => !o);
  };

  return (
    <View>
      <Pressable style={styles.field} onPress={toggle} testID={testID}>
        <Ionicons name="calendar-outline" size={16} color={financeColors.inkMuted} />
        <Text style={[styles.fieldText, !selected && styles.placeholder]} numberOfLines={1}>
          {selected ? label(selected) : placeholder}
        </Text>
        {clearable && selected ? (
          <Pressable onPress={() => { onChange(""); setOpen(false); }} hitSlop={8} testID={testID ? `${testID}-clear` : undefined}>
            <Ionicons name="close-circle" size={16} color={financeColors.inkFaint} />
          </Pressable>
        ) : null}
      </Pressable>
      {open ? (
        <View style={styles.panel}>
          <View style={styles.yearRow}>
            <Pressable onPress={() => setYear((y) => y - 1)} hitSlop={8} style={styles.yearBtn} testID={testID ? `${testID}-prev-year` : undefined}>
              <Ionicons name="chevron-back" size={18} color={financeColors.ink} />
            </Pressable>
            <Text style={styles.year}>{year}</Text>
            <Pressable onPress={() => setYear((y) => y + 1)} hitSlop={8} style={styles.yearBtn} testID={testID ? `${testID}-next-year` : undefined}>
              <Ionicons name="chevron-forward" size={18} color={financeColors.ink} />
            </Pressable>
          </View>
          <View style={styles.grid}>
            {MONTHS.map((m, i) => {
              const v = `${year}-${String(i + 1).padStart(2, "0")}`;
              const sel = v === selected;
              return (
                <Pressable
                  key={m}
                  onPress={() => { onChange(v); setOpen(false); }}
                  style={[styles.cell, sel && styles.cellSel]}
                  testID={testID ? `${testID}-${v}` : undefined}
                >
                  <Text style={[styles.cellText, sel && styles.cellTextSel]}>{m}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  field: { flexDirection: "row", alignItems: "center", gap: financeSpace.sm, borderWidth: 1, borderColor: financeColors.cardBorder, borderRadius: financeRadius.md, paddingHorizontal: financeSpace.md, minHeight: 48 },
  fieldText: { flex: 1, fontSize: 15, color: financeColors.ink },
  placeholder: { color: financeColors.inkFaint },
  panel: { marginTop: financeSpace.sm, borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, borderRadius: financeRadius.md, padding: financeSpace.sm, gap: financeSpace.sm },
  yearRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  yearBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  year: { fontSize: 15, fontWeight: "700", color: financeColors.ink },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  cell: { width: "30%", flexGrow: 1, minHeight: 40, borderRadius: financeRadius.pill, alignItems: "center", justifyContent: "center", borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder },
  cellSel: { backgroundColor: financeColors.ink, borderColor: financeColors.ink },
  cellText: { fontSize: 13, color: financeColors.ink },
  cellTextSel: { color: "#FBFBF6", fontWeight: "700" },
});
