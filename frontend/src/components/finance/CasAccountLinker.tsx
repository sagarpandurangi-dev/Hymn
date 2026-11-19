import { Pressable, StyleSheet, Text, View } from "react-native";

import { FoldCard } from "@/src/components/finance/foldUi";
import { reportMoney } from "@/src/components/finance/ReportBits";
import { lineKey } from "@/src/components/finance/CasPreviewCard";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

export type AccountChoice = { mode: "same"; lineKey: string | null } | { mode: "replaces" } | { mode: "other" };

type Props = {
  accounts: any[];
  lines: any[];
  choices: Record<string, AccountChoice>;
  onChange: (accountId: string, c: AccountChoice) => void;
};

/** "Is any of these the same as a fund in this statement?" — one choice per existing account. */
export default function CasAccountLinker({ accounts, lines, choices, onChange }: Props) {
  return (
    <View style={{ gap: financeSpace.md }} testID="cas-linker">
      <Text style={styles.q}>Is any of these the same as a fund in this statement?</Text>
      {accounts.map((a) => {
        const id = String(a.id);
        const c = choices[id] ?? { mode: "other" };
        const chip = (label: string, on: boolean, press: () => void, testID: string) => (
          <Pressable key={testID} onPress={press} style={[styles.chip, on && styles.chipOn]} testID={testID}>
            <Text style={[styles.chipText, on && styles.chipTextOn]}>{label}</Text>
          </Pressable>
        );
        return (
          <FoldCard key={id} testID={`cas-account-${id}`}>
            <View style={styles.card}>
              <Text style={styles.name}>{a.name ?? "Investment"}</Text>
              {a.current_value != null ? <Text style={styles.meta}>{reportMoney(a.currency ?? "INR", a.current_value)}</Text> : null}
              <View style={styles.chips}>
                {chip("This is the same fund as …", c.mode === "same", () => onChange(id, { mode: "same", lineKey: c.mode === "same" ? c.lineKey : null }), `cas-account-${id}-same`)}
                {chip("This statement replaces it", c.mode === "replaces", () => onChange(id, { mode: "replaces" }), `cas-account-${id}-replaces`)}
                {chip("Something else", c.mode === "other", () => onChange(id, { mode: "other" }), `cas-account-${id}-other`)}
              </View>
              {c.mode === "same" ? (
                <View style={styles.chips}>
                  {lines.map((l, i) => {
                    const k = lineKey(l, i);
                    return chip(l?.name ?? k, c.lineKey === k, () => onChange(id, { mode: "same", lineKey: k }), `cas-account-${id}-line-${i}`);
                  })}
                </View>
              ) : null}
            </View>
          </FoldCard>
        );
      })}
    </View>
  );
}

/** Turn per-account choices into the apply payload {links: {lineKey: accountId}, replaces: [accountId]}. */
export function toApplyPayload(choices: Record<string, AccountChoice>) {
  const links: Record<string, string> = {};
  const replaces: string[] = [];
  Object.entries(choices).forEach(([accountId, c]) => {
    if (c.mode === "same" && c.lineKey) links[c.lineKey] = accountId;
    if (c.mode === "replaces") replaces.push(accountId);
  });
  return { links, replaces };
}

const styles = StyleSheet.create({
  q: { fontSize: 15, fontWeight: "700", color: financeColors.ink },
  card: { padding: financeSpace.lg, gap: financeSpace.sm },
  name: { fontSize: 14, fontWeight: "700", color: financeColors.ink },
  meta: { fontSize: 12, color: financeColors.inkMuted },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: financeSpace.sm },
  chip: { minHeight: 40, paddingHorizontal: financeSpace.md, borderRadius: 999, borderWidth: 1, borderColor: financeColors.divider, justifyContent: "center" },
  chipOn: { backgroundColor: financeColors.ink, borderColor: financeColors.ink },
  chipText: { fontSize: 13, color: financeColors.ink },
  chipTextOn: { color: financeColors.card, fontWeight: "700" },
});
