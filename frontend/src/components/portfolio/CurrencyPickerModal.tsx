import { useMemo, useState } from "react";
import {
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";
import { ISO_4217_CURRENCIES } from "@/src/lib/portfolio/constants";

type Props = {
  visible: boolean;
  selected?: string | null;
  onSelect: (code: string) => void;
  onClose: () => void;
  testID?: string;
};

/**
 * Searchable ISO 4217 currency picker used by every Portfolio surface.
 * Full alphabetic code list; filters by code AND name; no network required.
 */
export default function CurrencyPickerModal({ visible, selected, onSelect, onClose, testID }: Props) {
  const [q, setQ] = useState("");

  const data = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return ISO_4217_CURRENCIES;
    return ISO_4217_CURRENCIES.filter(
      (c) => c.code.toLowerCase().includes(needle) || c.name.toLowerCase().includes(needle),
    );
  }, [q]);

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent={false}>
      <View style={styles.wrap} testID={testID || "currency-picker"}>
        <View style={styles.header}>
          <Pressable onPress={onClose} hitSlop={12} testID="currency-picker-close">
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.title}>Select Currency</Text>
          <View style={{ width: 22 }} />
        </View>
        <View style={styles.searchWrap}>
          <Ionicons name="search" size={16} color={colors.onSurfaceTertiary} />
          <TextInput
            style={styles.search}
            value={q}
            onChangeText={setQ}
            placeholder="Search code or name"
            placeholderTextColor={colors.onSurfaceTertiary}
            autoCorrect={false}
            autoCapitalize="characters"
            testID="currency-picker-search"
          />
        </View>
        <View style={{ flex: 1 }}>
          <FlatList
            data={data}
            keyExtractor={(item) => item.code}
            initialNumToRender={20}
            windowSize={7}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => {
              const isSel = selected === item.code;
              return (
                <Pressable
                  style={({ pressed }) => [styles.row, pressed && { opacity: 0.6 }, isSel && styles.rowSelected]}
                  onPress={() => {
                    onSelect(item.code);
                    onClose();
                  }}
                  testID={`currency-option-${item.code}`}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.code}>{item.code}</Text>
                    <Text style={styles.name}>{item.name}</Text>
                  </View>
                  {isSel && <Ionicons name="checkmark" size={18} color={colors.brandPrimary} />}
                </Pressable>
              );
            }}
          />
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xxxl,
    paddingBottom: spacing.md,
  },
  title: { fontFamily: fonts.displayBold, fontSize: 18, color: colors.onSurface, fontWeight: "700" },
  searchWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
  },
  search: { flex: 1, fontSize: 15, color: colors.onSurface },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowSelected: { backgroundColor: colors.surfaceSecondary },
  code: { fontSize: 15, color: colors.onSurface, fontWeight: "600" },
  name: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
});
