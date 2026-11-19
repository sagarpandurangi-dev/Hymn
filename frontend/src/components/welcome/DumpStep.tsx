import { useEffect, useRef, useState } from "react";
import { Text, TextInput, View } from "react-native";

import WelcomeShell, { StepNav } from "./WelcomeShell";
import InboxItemRow from "@/src/components/InboxItemRow";
import { api, ApiError, InboxDumpResponse } from "@/src/lib/api";
import { formStyles as fs } from "@/src/lib/formStyles";
import { getSaved, markSaved } from "@/src/lib/welcome";
import { colors, spacing } from "@/src/lib/theme";

const newDumpId = () =>
  `dump-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;

/** Brain dump through the existing flow: POST /inbox/dumps, then the sort step if it came back unsorted. */
export default function DumpStep({ nav }: { nav: StepNav }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InboxDumpResponse | null>(null);
  const pendingRef = useRef<{ text: string; id: string } | null>(null);
  const [alreadySent, setAlreadySent] = useState(false);

  useEffect(() => { getSaved().then((s) => setAlreadySent(s.includes("dump"))); }, []);

  const sortIt = async () => {
    const body = text.trim();
    if (!body) return;
    if (!pendingRef.current || pendingRef.current.text !== body) pendingRef.current = { text: body, id: newDumpId() };
    setBusy(true);
    setError("");
    try {
      let res = await api.createInboxDump({
        text: body,
        client_dump_id: pendingRef.current.id,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      if (res.dump.status === "unsorted") {
        res = await api.sortInboxDump(res.dump.id).catch(() => res);
      }
      pendingRef.current = null;
      await markSaved("dump");
      setResult(res);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't save that. Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <WelcomeShell nav={nav} title={`Sorted into ${result.items.length} ${result.items.length === 1 ? "thing" : "things"}`} subtitle={result.ack} primaryLabel="Continue" onPrimary={nav.next}>
        <View style={{ gap: spacing.sm }} testID="welcome-dump-result">
          {result.items.map((it) => <InboxItemRow key={it.id} text={it.text} category={it.category} testID={`welcome-dump-item-${it.id}`} />)}
        </View>
      </WelcomeShell>
    );
  }

  if (alreadySent) {
    return (
      <WelcomeShell nav={nav} title="Empty your head" primaryLabel="Continue" onPrimary={nav.next}>
        <Text style={{ fontSize: 14, color: colors.onSurfaceSecondary }} testID="welcome-already-saved">
          Already sorted. Add more any time with the + button.
        </Text>
      </WelcomeShell>
    );
  }

  return (
    <WelcomeShell nav={nav} title="Empty your head" subtitle="Type everything on your mind. Hymn will sort it." primaryLabel="Sort it" onPrimary={sortIt} primaryDisabled={!text.trim()} busy={busy} error={error}>
      <TextInput
        style={[fs.notes, { minHeight: 240, textAlignVertical: "top", fontSize: 16 }]}
        value={text}
        onChangeText={setText}
        multiline
        placeholder="Call the bank, Amma's birthday gift, learn guitar…"
        placeholderTextColor={colors.onSurfaceTertiary}
        testID="welcome-dump-input"
      />
      {busy ? <Text style={{ marginTop: spacing.md, color: colors.onSurfaceSecondary }}>Sorting…</Text> : null}
    </WelcomeShell>
  );
}
