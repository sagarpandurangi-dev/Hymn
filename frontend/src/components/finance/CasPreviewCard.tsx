import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import { FoldCard, FoldPill } from "@/src/components/finance/foldUi";
import { reportMoney } from "@/src/components/finance/ReportBits";
import { dateLabel } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

// Preview fields are read defensively; the server shape may use slightly different names.
export const lineKey = (l: any, i: number): string => String(l?.key ?? l?.id ?? `${l?.folio ?? ""}:${l?.name ?? i}`);
export const periodText = (p: any): string => {
  const per = p?.period;
  if (typeof per === "string") return per;
  const from = per?.from ?? per?.start ?? p?.period_from ?? p?.from_date;
  const to = per?.to ?? per?.end ?? p?.period_to ?? p?.to_date;
  return [from, to].filter(Boolean).map((d: string) => (/^\d{4}-\d{2}-\d{2}$/.test(d) ? dateLabel(d) : d)).join(" – ");
};
const changeText = (c: any): string => {
  if (!c) return "";
  if (typeof c === "string" || typeof c === "number") return String(c);
  if (c.message) return String(c.message);
  return Object.entries(c).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ");
};
const checkText = (c: any): string => (typeof c === "string" ? c : c?.message ?? c?.reason ?? (c ? "Please check this line." : ""));

const ACTION: Record<string, { label: string; tone: "ok" | "info" | "neutral" | "warn" }> = {
  new: { label: "New", tone: "ok" },
  update: { label: "Update", tone: "info" },
  same: { label: "No change", tone: "neutral" },
  older: { label: "Older than what Hymn has", tone: "warn" },
};

function LineRow({ line, currency, testID }: { line: any; currency: string; testID: string }) {
  const [open, setOpen] = useState(false);
  const items: any[] = line?.items ?? line?.holdings ?? [];
  const expandable = ["stock", "bond", "nps"].includes(String(line?.kind)) && items.length > 0;
  const act = ACTION[String(line?.action)];
  const meta = [
    line?.folio ? `Folio ${line.folio}` : "",
    line?.units != null ? `${line.units} units` : "",
    line?.price != null || line?.nav != null ? `@ ${reportMoney(currency, line.price ?? line.nav)}` : "",
    line?.valued_on ? `on ${dateLabel(line.valued_on)}` : "",
  ].filter(Boolean).join(" · ");
  const check = checkText(line?.check);

  return (
    <View style={styles.line} testID={testID}>
      <Pressable onPress={expandable ? () => setOpen(!open) : undefined} disabled={!expandable} style={styles.lineTop}>
        <View style={{ flex: 1, gap: 2 }}>
          <View style={styles.titleRow}>
            {expandable ? <Ionicons name={open ? "chevron-down" : "chevron-forward"} size={12} color={financeColors.inkMuted} /> : null}
            <Text style={styles.name} numberOfLines={2}>{line?.name ?? "—"}</Text>
          </View>
          {meta ? <Text style={styles.meta}>{meta}</Text> : null}
          <View style={styles.titleRow}>
            {act ? <FoldPill label={act.label} tone={act.tone} size="xs" /> : null}
            {line?.action === "update" && changeText(line?.change) ? <Text style={styles.meta}>{changeText(line.change)}</Text> : null}
          </View>
        </View>
        <Text style={styles.value}>{reportMoney(currency, line?.value)}</Text>
      </Pressable>
      {check ? (
        <View style={styles.warn} testID={`${testID}-check`}>
          <Ionicons name="alert-circle-outline" size={14} color={financeColors.pillWarnInk} />
          <Text style={styles.warnText}>{check}</Text>
        </View>
      ) : null}
      {open ? items.map((it, j) => (
        <View key={j} style={styles.item}>
          <Text style={styles.itemName} numberOfLines={1}>{it?.name ?? it?.isin ?? "—"}</Text>
          <Text style={styles.itemVal}>{it?.units != null ? `${it.units} × ` : ""}{reportMoney(currency, it?.value)}</Text>
        </View>
      )) : null}
    </View>
  );
}

/** Statement header (source, period, investor, total) and every line. */
export default function CasPreviewCard({ preview }: { preview: any }) {
  const currency = preview?.currency ?? "INR";
  const lines: any[] = preview?.lines ?? [];
  const investor = preview?.investor_name ?? preview?.investor?.name ?? preview?.investor;
  return (
    <FoldCard testID="cas-preview">
      <View style={styles.head}>
        <Text style={styles.source}>{preview?.source ?? "Statement"}{periodText(preview) ? ` · ${periodText(preview)}` : ""}</Text>
        {investor ? <Text style={styles.investor} testID="cas-investor">For {String(investor)}</Text> : null}
        <Text style={styles.total} testID="cas-total">{reportMoney(currency, preview?.total ?? preview?.total_value)}</Text>
      </View>
      {lines.map((l, i) => <LineRow key={lineKey(l, i)} line={l} currency={currency} testID={`cas-line-${i}`} />)}
    </FoldCard>
  );
}

const styles = StyleSheet.create({
  head: { padding: financeSpace.lg, gap: 4 },
  source: { fontSize: 13, color: financeColors.inkMuted, fontWeight: "600" },
  investor: { fontSize: 16, fontWeight: "700", color: financeColors.ink },
  total: { fontSize: 24, fontWeight: "700", color: financeColors.ink },
  line: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: financeColors.divider, paddingHorizontal: financeSpace.lg, paddingVertical: financeSpace.md },
  lineTop: { flexDirection: "row", gap: financeSpace.md, alignItems: "flex-start" },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  name: { fontSize: 14, fontWeight: "600", color: financeColors.ink, flexShrink: 1 },
  meta: { fontSize: 12, color: financeColors.inkMuted },
  value: { fontSize: 14, fontWeight: "700", color: financeColors.ink },
  warn: { flexDirection: "row", gap: 6, alignItems: "flex-start", marginTop: financeSpace.sm },
  warnText: { flex: 1, fontSize: 12, color: financeColors.ink },
  item: { flexDirection: "row", justifyContent: "space-between", paddingLeft: financeSpace.lg, paddingTop: 6, gap: financeSpace.md },
  itemName: { flex: 1, fontSize: 12, color: financeColors.inkMuted },
  itemVal: { fontSize: 12, color: financeColors.ink },
});
