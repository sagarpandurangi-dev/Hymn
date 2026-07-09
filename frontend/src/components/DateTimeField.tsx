import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { useState } from "react";
import DateTimePicker, { DateTimePickerEvent } from "@react-native-community/datetimepicker";
import { Ionicons } from "@expo/vector-icons";
import { colors, radius, spacing } from "@/src/lib/theme";

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);

function toDateString(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function toTimeString(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function parseDate(s: string): Date {
  if (s && /^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const [y, m, d] = s.split("-").map((v) => parseInt(v, 10));
    return new Date(y, m - 1, d);
  }
  return new Date();
}
function parseTime(s: string): Date {
  const d = new Date();
  if (s && /^\d{2}:\d{2}$/.test(s)) {
    const [h, m] = s.split(":").map((v) => parseInt(v, 10));
    d.setHours(h, m, 0, 0);
  }
  return d;
}

type Props = {
  mode: "date" | "time";
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  clearable?: boolean;
  testID?: string;
};

export default function DateTimeField({ mode, value, onChange, placeholder, clearable, testID }: Props) {
  const [showPicker, setShowPicker] = useState(false);

  const label = value || placeholder || (mode === "date" ? "Choose date" : "Choose time");
  const hasValue = !!value;
  const iconName: "calendar-outline" | "time-outline" = mode === "date" ? "calendar-outline" : "time-outline";

  // ---------- Web fallback: use native <input type="date|time"> ----------
  if (Platform.OS === "web") {
    // Rendered via createElement to avoid RN-Web warning about unknown DOM props.
    return (
      <View style={styles.wrap} testID={testID}>
        {/* @ts-expect-error web-only element */}
        <input
          type={mode === "date" ? "date" : "time"}
          value={value}
          onChange={(e: any) => onChange(e.target.value)}
          style={{
            flex: 1,
            border: "none",
            outline: "none",
            background: "transparent",
            fontSize: 15,
            color: colors.onSurface,
            padding: 0,
            fontFamily: "inherit",
          }}
        />
        {clearable && hasValue ? (
          <Pressable onPress={() => onChange("")} hitSlop={8} testID={testID ? `${testID}-clear` : undefined}>
            <Ionicons name="close-circle" size={18} color={colors.onSurfaceTertiary} />
          </Pressable>
        ) : (
          <Ionicons name={iconName} size={18} color={colors.onSurfaceTertiary} />
        )}
      </View>
    );
  }

  // ---------- Native (iOS / Android) ----------
  const onNativeChange = (event: DateTimePickerEvent, selected?: Date) => {
    // Android dismiss => event.type === "dismissed"; iOS uses an inline spinner and stays open.
    if (Platform.OS === "android") {
      setShowPicker(false);
      if (event.type === "set" && selected) {
        onChange(mode === "date" ? toDateString(selected) : toTimeString(selected));
      }
    } else if (selected) {
      onChange(mode === "date" ? toDateString(selected) : toTimeString(selected));
    }
  };

  const initialDate = mode === "date" ? parseDate(value) : parseTime(value);

  return (
    <>
      <Pressable style={styles.wrap} onPress={() => setShowPicker(true)} testID={testID}>
        <Text style={[styles.text, !hasValue && styles.placeholder]}>{label}</Text>
        {clearable && hasValue ? (
          <Pressable
            onPress={(e) => { e.stopPropagation(); onChange(""); }}
            hitSlop={8}
            testID={testID ? `${testID}-clear` : undefined}
          >
            <Ionicons name="close-circle" size={18} color={colors.onSurfaceTertiary} />
          </Pressable>
        ) : (
          <Ionicons name={iconName} size={18} color={colors.onSurfaceTertiary} />
        )}
      </Pressable>

      {showPicker && (
        <View testID={testID ? `${testID}-native-picker` : undefined}>
          <DateTimePicker
            value={initialDate}
            mode={mode}
            display={Platform.OS === "ios" ? "spinner" : "default"}
            onChange={onNativeChange}
          />
          {Platform.OS === "ios" && (
            <View style={styles.iosDoneRow}>
              <Pressable onPress={() => setShowPicker(false)} style={styles.iosDoneBtn} testID={testID ? `${testID}-done` : undefined}>
                <Text style={styles.iosDoneText}>Done</Text>
              </Pressable>
            </View>
          )}
        </View>
      )}
    </>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md, minHeight: 46,
  },
  text: { flex: 1, fontSize: 15, color: colors.onSurface },
  placeholder: { color: colors.onSurfaceTertiary },
  iosDoneRow: { alignItems: "flex-end", paddingHorizontal: spacing.md, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary },
  iosDoneBtn: { paddingHorizontal: spacing.lg, paddingVertical: 6 },
  iosDoneText: { color: colors.brandPrimary, fontSize: 15, fontWeight: "600" },
});
