import { useEffect, useState } from "react";
import { ActivityIndicator, Linking, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import * as Notifications from "expo-notifications";

import WelcomeShell, { StepNav } from "./WelcomeShell";
import AccountEditor, { AccountDraft } from "@/src/components/portfolio/AccountEditor";
import { api, ApiError, InboxItem } from "@/src/lib/api";
import { registerForPushNotifications } from "@/src/lib/push";
import { ACCOUNT_PRESET_BY_CODE } from "@/src/lib/portfolio/constants";
import { formatMoney } from "@/src/lib/finance/format";
import { colors, radius, spacing } from "@/src/lib/theme";

export function MoneyStep({ nav }: { nav: StepNav }) {
  const [open, setOpen] = useState(false);
  const [added, setAdded] = useState<AccountDraft | null>(null);

  // Same payload as the Portfolio "Add account" form.
  const save = async (draft: AccountDraft) => {
    const preset = ACCOUNT_PRESET_BY_CODE[draft.account_type];
    await api.createFinancialAccount({
      account_type: draft.account_type,
      name: draft.name,
      currency: draft.currency,
      current_value: draft.current_value,
      liquidity_type: preset.liquidity_type,
      fixed_or_flexible: preset.fixed_or_flexible,
    });
    setAdded(draft);
    setOpen(false);
  };

  return (
    <WelcomeShell
      nav={nav}
      title="Add your main bank account"
      subtitle="Optional. It's the starting point for your money book."
      primaryLabel={added ? "Continue" : "Add bank account"}
      onPrimary={added ? nav.next : () => setOpen(true)}
    >
      {added ? (
        <View style={styles.addedRow} testID="welcome-money-added">
          <Ionicons name="checkmark-circle" size={22} color={colors.success} />
          <Text style={styles.addedText}>{added.name} · {added.currency} {formatMoney(added.current_value)}</Text>
        </View>
      ) : null}
      <AccountEditor
        visible={open}
        initial={{ account_type: "bank", name: "", currency: "INR", current_value: "" }}
        defaultCurrency="INR"
        onSubmit={save}
        onClose={() => setOpen(false)}
      />
    </WelcomeShell>
  );
}

export function NotifyStep({ nav }: { nav: StepNav }) {
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [note, setNote] = useState("");

  const turnOn = async () => {
    if (Platform.OS === "web") { nav.next(); return; } // reminders only work in the phone app
    setBusy(true);
    try {
      const before = await Notifications.getPermissionsAsync();
      if (before.status !== "granted" && !before.canAskAgain) { setBlocked(true); return; }
      await registerForPushNotifications(); // asks (if allowed to) and registers this device
      const after = await Notifications.getPermissionsAsync();
      if (after.status === "granted") nav.next();
      else if (!after.canAskAgain) setBlocked(true);
      else setNote("Reminders are off. You can turn them on later.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <WelcomeShell nav={nav} title="Gentle reminders" subtitle="A few a day at most, never during your quiet hours." primaryLabel={blocked ? "Continue" : "Turn on reminders"} onPrimary={blocked ? nav.next : turnOn} busy={busy}>
      <View style={styles.preview} testID="welcome-notify-preview">
        <View style={styles.previewHead}>
          <Ionicons name="notifications-outline" size={16} color={colors.brandPrimary} />
          <Text style={styles.previewApp}>Hymn · now</Text>
        </View>
        <Text style={styles.previewText}>Amma&apos;s birthday is tomorrow</Text>
        <Text style={styles.previewSub}>Want to plan a call or a gift?</Text>
      </View>
      {blocked ? (
        <View style={{ marginTop: spacing.lg, gap: spacing.sm }}>
          <Text style={styles.note}>Notifications are turned off for Hymn. You can allow them in Settings.</Text>
          <Pressable onPress={() => Linking.openSettings()} style={styles.settingsBtn} testID="welcome-notify-open-settings">
            <Text style={styles.settingsText}>Open Settings</Text>
          </Pressable>
        </View>
      ) : note ? <Text style={[styles.note, { marginTop: spacing.lg }]}>{note}</Text> : null}
    </WelcomeShell>
  );
}

export function PayoffStep({ nav, onFinish, onSignOut }: { nav: StepNav; onFinish: (dest: "today" | "planner") => Promise<void>; onSignOut: () => void }) {
  const [freeHours, setFreeHours] = useState<string | null>(null);
  const [things, setThings] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.getTimeReport().then((r) => setFreeHours(r?.commitments?.free_hours ?? null)).catch(() => undefined),
      api.getInboxReview().then((r) => setThings((r.items || []).slice(0, 3))).catch(() => undefined),
    ]).finally(() => setLoading(false));
  }, []);

  const finish = async (dest: "today" | "planner") => {
    setBusy(true);
    setError("");
    try {
      await onFinish(dest);
    } catch (e) {
      setError((e as ApiError).message || "Couldn't finish setup. Try again.");
      setBusy(false);
    }
  };

  const hours = freeHours !== null ? String(Math.round(Number(freeHours))) : null;

  return (
    <WelcomeShell
      nav={nav}
      hideSkip
      title={hours !== null ? `You have ${hours} free hours this week` : "You're all set"}
      primaryLabel="Go to Today"
      onPrimary={() => finish("today")}
      busy={busy}
      error={error}
      secondary={{ label: "Tell Hymn one thing you want", onPress: () => finish("planner"), testID: "welcome-tell-hymn" }}
    >
      {loading ? <ActivityIndicator color={colors.brandPrimary} /> : (
        <View testID="welcome-payoff">
          <Text style={styles.sectionTitle}>Your 3 things for today</Text>
          {things.length === 0 ? (
            <Text style={styles.note}>Nothing yet. Add a brain dump any time with the + button.</Text>
          ) : things.map((t, i) => (
            <View key={t.id} style={styles.thing} testID={`welcome-thing-${i}`}>
              <Text style={styles.thingNum}>{i + 1}</Text>
              <Text style={styles.thingText}>{t.text}</Text>
            </View>
          ))}
        </View>
      )}
      {error ? (
        <Pressable onPress={onSignOut} style={[styles.settingsBtn, { marginTop: spacing.xl }]} testID="welcome-sign-out">
          <Text style={styles.settingsText}>Sign out</Text>
        </Pressable>
      ) : null}
    </WelcomeShell>
  );
}

const styles = StyleSheet.create({
  addedRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  addedText: { flex: 1, fontSize: 15, fontWeight: "600", color: colors.onSurface },
  preview: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.xs, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.borderStrong },
  previewHead: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  previewApp: { fontSize: 12, color: colors.onSurfaceTertiary },
  previewText: { fontSize: 16, fontWeight: "600", color: colors.onSurface },
  previewSub: { fontSize: 14, color: colors.onSurfaceSecondary },
  note: { fontSize: 14, color: colors.onSurfaceSecondary, lineHeight: 20 },
  settingsBtn: { alignSelf: "flex-start", minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.borderStrong, justifyContent: "center" },
  settingsText: { fontSize: 15, fontWeight: "600", color: colors.onSurface },
  sectionTitle: { fontSize: 15, fontWeight: "600", color: colors.onSurface, marginBottom: spacing.md },
  thing: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md, paddingVertical: spacing.sm },
  thingNum: { width: 24, height: 24, borderRadius: 12, textAlign: "center", lineHeight: 24, fontSize: 13, fontWeight: "700", color: colors.onBrandPrimary, backgroundColor: colors.brandPrimary, overflow: "hidden" },
  thingText: { flex: 1, fontSize: 15, lineHeight: 22, color: colors.onSurface },
});
