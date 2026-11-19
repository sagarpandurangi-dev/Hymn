/**
 * Tiny markdown renderer for planner replies: headings, **bold**, bullet and
 * numbered lists, and simple pipe tables (shown as label — value lines).
 */
import { StyleSheet, Text, View } from "react-native";

import { colors, spacing } from "@/src/lib/theme";

function Inline({ text, style }: { text: string; style?: any }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean);
  return (
    <Text style={[styles.p, style]}>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? <Text key={i} style={styles.bold}>{p.slice(2, -2)}</Text> : p.replace(/(^|\s)_([^_]+)_/g, "$1$2"),
      )}
    </Text>
  );
}

export default function SimpleMarkdown({ text }: { text: string }) {
  const lines = (text || "").split("\n");
  const out: React.ReactNode[] = [];
  let tableHeaderSeen = false;
  lines.forEach((raw, i) => {
    const line = raw.trimEnd();
    if (!line.trim()) { tableHeaderSeen = false; out.push(<View key={i} style={{ height: spacing.sm }} />); return; }
    if (line.trim().startsWith("|")) {
      const cells = line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) return; // separator row
      if (!tableHeaderSeen) { tableHeaderSeen = true; return; } // header row
      out.push(
        <View key={i} style={styles.tableRow}>
          <Inline text={cells[0] ?? ""} style={styles.bold} />
          {cells.slice(1).map((c, j) => <Inline key={j} text={c} style={styles.muted} />)}
        </View>,
      );
      return;
    }
    const h = line.match(/^#{1,6}\s+(.*)$/);
    if (h) { out.push(<Inline key={i} text={h[1]} style={styles.h} />); return; }
    const b = line.match(/^(\s*)[-*•]\s+(.*)$/);
    if (b) {
      out.push(<View key={i} style={[styles.li, { paddingLeft: b[1].length > 0 ? spacing.lg : 0 }]}><Text style={styles.p}>•</Text><View style={{ flex: 1 }}><Inline text={b[2]} /></View></View>);
      return;
    }
    const n = line.match(/^(\s*)(\d+)[.)]\s+(.*)$/);
    if (n) {
      out.push(<View key={i} style={styles.li}><Text style={styles.p}>{n[2]}.</Text><View style={{ flex: 1 }}><Inline text={n[3]} /></View></View>);
      return;
    }
    out.push(<Inline key={i} text={line} />);
  });
  return <View>{out}</View>;
}

const styles = StyleSheet.create({
  p: { fontSize: 15, lineHeight: 22, color: colors.onSurface },
  bold: { fontWeight: "700" },
  muted: { color: colors.onSurfaceSecondary, fontSize: 14 },
  h: { fontSize: 16, fontWeight: "700", marginTop: spacing.xs },
  li: { flexDirection: "row", gap: spacing.sm, marginTop: 2 },
  tableRow: { borderLeftWidth: 2, borderLeftColor: colors.brandTertiary, paddingLeft: spacing.md, marginVertical: 4, gap: 2 },
});
