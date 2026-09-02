import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/lib/api";
import AccountPickerModal from "@/src/components/AccountPickerModal";
import DateTimeField from "@/src/components/DateTimeField";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";
import { formatMoney } from "@/src/lib/finance/format";

// Correction 2: this screen is the pending-event resolution journey.
// Users land here from the Finance "Pending account" warning. They can
// see WHY the event is pending, pick a same-currency asset account,
// confirm/correct when it occurred, save it, and return to Finance
// with the warning removed.

function pad(n: number, w = 2) { return String(n).padStart(w, "0"); }

// Construct a device-local, timezone-aware ISO 8601 timestamp from a
// YYYY-MM-DD date at 12:00 local time. The backend normalises to UTC.
function localIsoAtNoon(dateYmd: string): string {
  const [y, m, d] = dateYmd.split("-").map((v) => parseInt(v, 10));
  const dt = new Date(y, (m || 1) - 1, d || 1, 12, 0, 0);
  const off = -dt.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const oh = pad(Math.floor(Math.abs(off) / 60));
  const om = pad(Math.abs(off) % 60);
  return `${pad(dt.getFullYear(), 4)}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}:${pad(dt.getSeconds())}${sign}${oh}:${om}`;
}

export default function PendingEventDetail() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [ev, setEv] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [accountLabel, setAccountLabel] = useState<string>("Choose account");
  const [accountPickerOpen, setAccountPickerOpen] = useState(false);
  const [eventDate, setEventDate] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.listFinancialEvents({ limit: 500 });
      const found = (list || []).find((e: any) => e.id === id);
      if (!found) {
        Alert.alert("Not found", "This event no longer exists.");
        router.back();
        return;
      }
      setEv(found);
      setAccountId(found.account_id || null);
      setEventDate(found.event_date || "");
      if (found.account_id) {
        try {
          const rows = await api.listFinancialAccounts();
          const m = rows.find((r) => r.id === found.account_id);
          setAccountLabel(m ? `${m.name} (${m.currency})` : "Account selected");
        } catch { setAccountLabel("Account selected"); }
      } else {
        setAccountLabel("Choose account");
      }
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not load event");
    }
    setLoading(false);
  }, [id, router]);

  useEffect(() => { load(); }, [load]);

  const reason = useMemo(() => {
    if (!ev) return "";
    if (ev.lifecycle_status === "pending_account_assignment") {
      return "This event doesn't have an asset account attached yet. Pick the account it came from so Finance can apply it to your balance.";
    }
    if (ev.lifecycle_status === "pending_deduplication") {
      return "This event looks like a duplicate. Resolve it through the deduplication journey — not here.";
    }
    if (ev.review_reason === "missing_occurred_at") {
      return "This event is confirmed but the exact moment it occurred is unknown. Confirm the date so Finance can decide which snapshot it applies to.";
    }
    return "This event needs your review.";
  }, [ev]);

  const canSave = !!ev && ev.lifecycle_status !== "pending_deduplication" && !!accountId && !!eventDate;

  const save = async () => {
    if (!ev || !canSave) return;
    setBusy(true);
    try {
      await api.patchEventAssignment(ev.id, {
        account_id: accountId,
        // Correction 2: send a tz-aware ISO — anchor the transaction
        // at local noon of the reported calendar date so it can't fall
        // into the previous day for eastern hemispheres or the next
        // day for western hemispheres.
        occurred_at: localIsoAtNoon(eventDate),
        event_date: eventDate,
      });
      router.replace("/(tabs)/finance");
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "");
      setBusy(false);
    }
  };

  if (loading || !ev) return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Pending event" />
      <ActivityIndicator style={{ marginTop: 40 }} color={financeColors.ink} />
    </SafeAreaView>
  );

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Pending event" subtitle={ev.description || ""} />
      <ScrollView contentContainerStyle={{ padding: financeSpace.lg, gap: financeSpace.md }}>
        <FoldCard>
          <FoldRow label="Amount" right={<Text style={styles.value}>{ev.currency} {formatMoney(ev.amount)}</Text>} />
          <FoldRow label="Direction" right={<Text style={styles.value}>{ev.direction}</Text>} />
          <FoldRow label="Status" right={<Text style={styles.value}>{ev.lifecycle_status}</Text>} />
        </FoldCard>

        <Text style={styles.reason} testID="pending-event-reason">{reason}</Text>

        {ev.lifecycle_status !== "pending_deduplication" ? (
          <>
            <Text style={styles.label}>PAYING ACCOUNT</Text>
            <Pressable style={styles.input} onPress={() => setAccountPickerOpen(true)} testID="pending-event-account">
              <Text style={{ color: accountId ? financeColors.ink : financeColors.inkFaint }}>{accountLabel}</Text>
            </Pressable>

            <Text style={styles.label}>WHEN IT OCCURRED</Text>
            <DateTimeField mode="date" value={eventDate} onChange={setEventDate} testID="pending-event-date" />

            <Pressable style={[styles.primary, (!canSave || busy) && { opacity: 0.5 }]} onPress={save} disabled={!canSave || busy} testID="pending-event-save">
              <Text style={styles.primaryText}>Save and apply</Text>
            </Pressable>
          </>
        ) : (
          <Pressable style={styles.primary} onPress={() => router.push("/finance/reconcile")} testID="pending-event-open-dedupe">
            <Text style={styles.primaryText}>Open deduplication</Text>
          </Pressable>
        )}
      </ScrollView>

      <AccountPickerModal
        visible={accountPickerOpen}
        currency={ev.currency}
        selectedId={accountId}
        onSelect={async (aid) => {
          setAccountId(aid);
          if (!aid) { setAccountLabel("Assign later"); return; }
          try {
            const rows = await api.listFinancialAccounts();
            const m = rows.find((r) => r.id === aid);
            setAccountLabel(m ? `${m.name} (${m.currency})` : "Account selected");
          } catch { setAccountLabel("Account selected"); }
        }}
        onClose={() => setAccountPickerOpen(false)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  value: { color: financeColors.ink, fontSize: 14 },
  label: { color: financeColors.inkFaint, fontSize: 11, letterSpacing: 1, marginTop: financeSpace.md },
  input: { borderWidth: StyleSheet.hairlineWidth, borderColor: financeColors.cardBorder, borderRadius: 12, padding: financeSpace.md, backgroundColor: financeColors.surface },
  reason: { color: financeColors.ink, fontSize: 14, lineHeight: 20 },
  primary: { backgroundColor: financeColors.ink, borderRadius: 12, paddingVertical: financeSpace.md, alignItems: "center", marginTop: financeSpace.lg },
  primaryText: { color: financeColors.surface, fontSize: 14, fontWeight: "600" },
});
