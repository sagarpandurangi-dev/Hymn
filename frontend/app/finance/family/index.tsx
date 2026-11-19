import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import { useAuth } from "@/src/lib/AuthContext";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import FamilyMemberSheet from "@/src/components/finance/FamilyMemberSheet";
import { FoldCard, FoldPill, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { reportMoney } from "@/src/components/finance/ReportBits";
import { lifeStyles as s } from "@/src/components/finance/lifeObjects";
import { findMe, groupLabel, loadFamilyItems, loadMyMemberId, relationLabel, saveFamilyItems, saveMyMemberId, SavedFamilyItem } from "@/src/lib/family";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

const SHARE_OPTIONS = [
  { code: "total" as const, label: "Share my total" },
  { code: "full" as const, label: "Share my breakdown" },
];

const confirm = (title: string, body: string, ok: () => void) => {
  if (Platform.OS === "web") { if (window.confirm(`${title}\n\n${body}`)) ok(); return; }
  Alert.alert(title, body, [{ text: "Cancel", style: "cancel" }, { text: title, style: "destructive", onPress: ok }]);
};

export default function FamilyScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [data, setData] = useState<any>(null);
  const [items, setItems] = useState<SavedFamilyItem[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [sheet, setSheet] = useState<"invite" | "add" | null>(null);
  const [choosing, setChoosing] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [myId, setMyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.getFamily();
      setData(d);
      setItems(d?.family?.id ? await loadFamilyItems(d.family.id) : []);
      setMyId(d?.family?.id ? await loadMyMemberId(d.family.id) : null);
      setError("");
    } catch (e) {
      setError((e as ApiError).message || "Couldn't load your family.");
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const run = async (tag: string, fn: () => Promise<any>, msg = "") => {
    setBusy(tag);
    setError("");
    setNotice("");
    try {
      await fn();
      if (msg) setNotice(msg);
      await load();
    } catch (e) {
      setError((e as ApiError).message || "Something went wrong. Try again.");
    } finally {
      setBusy("");
    }
  };

  const family = data?.family;
  const members: any[] = data?.members ?? [];
  const invites: any[] = data?.invites_for_me ?? [];
  const me = findMe(members, family, user, myId);
  const nameOf = (id: string) => members.find((m) => m.id === id)?.name ?? "Someone";

  const removeItem = (it: SavedFamilyItem) =>
    confirm("Delete", `Remove “${it.name}” from the family net worth?`, () =>
      run(`del-${it.id}`, async () => {
        try {
          await api.deleteFamilyItem(it.id);
        } catch (e) {
          if ((e as ApiError).status !== 404) throw e;
        }
        const next = items.filter((x) => x.id !== it.id);
        await saveFamilyItems(family.id, next);
      }, "Entry deleted."));

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]} testID="family-screen">
      <FinanceHeader title="Family net worth" subtitle="What your family owns and owes together" />
      <ScrollView
        contentContainerStyle={s.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        {!data ? (
          error ? <Text style={s.error}>{error}</Text> : <ActivityIndicator color={financeColors.inkMuted} />
        ) : (
          <>
            {notice ? <Text style={[s.body, { color: financeColors.positive }]} testID="family-notice">{notice}</Text> : null}
            {error ? <Text style={s.error} testID="family-error">{error}</Text> : null}

            {invites.length > 0 ? (
              <View testID="family-invites">
                <FoldSectionHeader label="Invites for you" />
                <FoldCard>
                  {invites.map((inv, i) => (
                    <View key={inv.id} style={[s.pad, i > 0 && { borderTopWidth: 1, borderTopColor: financeColors.divider }]}>
                      <Text style={s.h}>Join a family as {relationLabel(inv.relation).toLowerCase()}</Text>
                      {choosing === inv.id ? (
                        <>
                          <Text style={s.body}>What can the family see?</Text>
                          {SHARE_OPTIONS.map((o) => (
                            <Pressable key={o.code} style={s.secondary} disabled={!!busy} onPress={() => run(`acc-${inv.id}`, async () => { await api.acceptFamilyInvite(inv.id, o.code); if (inv.household_id) await saveMyMemberId(inv.household_id, inv.id); }, "You've joined the family.")} testID={`family-accept-${o.code}-${inv.id}`}>
                              <Text style={s.secondaryText}>{o.label}</Text>
                            </Pressable>
                          ))}
                          <Pressable onPress={() => setChoosing(null)} style={{ minHeight: 40, alignItems: "center", justifyContent: "center" }}>
                            <Text style={s.body}>Back</Text>
                          </Pressable>
                        </>
                      ) : (
                        <View style={{ flexDirection: "row", gap: financeSpace.sm }}>
                          <Pressable style={[s.primary, { flex: 1 }]} onPress={() => setChoosing(inv.id)} disabled={!!busy} testID={`family-accept-${inv.id}`}>
                            <Text style={s.primaryText}>Accept</Text>
                          </Pressable>
                          <Pressable style={[s.secondary, { flex: 1 }]} onPress={() => run(`dec-${inv.id}`, () => api.declineFamilyInvite(inv.id), "Invite declined.")} disabled={!!busy} testID={`family-decline-${inv.id}`}>
                            <Text style={s.secondaryText}>Decline</Text>
                          </Pressable>
                        </View>
                      )}
                    </View>
                  ))}
                </FoldCard>
              </View>
            ) : null}

            {!family ? (
              <FoldCard testID="family-empty">
                <View style={s.pad}>
                  <Ionicons name="people-outline" size={22} color={financeColors.ink} />
                  <Text style={s.h}>See your family&apos;s net worth together</Text>
                  <Text style={s.body}>Add your spouse, parents or children — with or without the app — and the homes, loans and savings you share.</Text>
                  <Pressable style={[s.primary, { marginTop: 8 }, !!busy && { opacity: 0.5 }]} disabled={!!busy} onPress={() => run("create", () => api.createFamily(), "Your family is ready.")} testID="family-create">
                    {busy === "create" ? <ActivityIndicator color={financeColors.card} /> : <Text style={s.primaryText}>Create my family</Text>}
                  </Pressable>
                </View>
              </FoldCard>
            ) : (
              <>
                <FoldCard>
                  <FoldRow first label="Family net worth" meta="A column for each person and the family total" onPress={() => router.push("/finance/family/net-worth" as any)} chevron strong testID="family-open-net-worth" />
                </FoldCard>

                <View>
                  <FoldSectionHeader label="Members" />
                  <FoldCard testID="family-members">
                    {members.map((m, i) => (
                      <FoldRow
                        key={m.id}
                        first={i === 0}
                        label={m.id === me?.id ? `${m.name} (you)` : m.name}
                        meta={[relationLabel(m.relation), m.kind === "notional" ? "Without the app" : ""].filter(Boolean).join(" · ")}
                        right={m.status === "invited" ? <FoldPill label="Invited" tone="warn" size="xs" /> : m.kind === "user" ? <FoldPill label={m.share === "full" ? "Breakdown" : "Total only"} tone="info" size="xs" /> : undefined}
                        testID={`family-member-${m.id}`}
                      />
                    ))}
                  </FoldCard>
                  <View style={{ gap: financeSpace.sm, marginTop: financeSpace.md }}>
                    <Pressable style={s.secondary} onPress={() => setSheet("invite")} testID="family-invite-open">
                      <Ionicons name="paper-plane-outline" size={18} color={financeColors.ink} />
                      <Text style={s.secondaryText}>Invite by Pamphlet ID</Text>
                    </Pressable>
                    <Pressable style={s.secondary} onPress={() => setSheet("add")} testID="family-add-member-open">
                      <Ionicons name="person-add-outline" size={18} color={financeColors.ink} />
                      <Text style={s.secondaryText}>Add someone without the app</Text>
                    </Pressable>
                  </View>
                </View>

                <View>
                  <FoldSectionHeader
                    label="Entries"
                    hint="Homes, savings and loans owned by one person or jointly"
                    action={{ label: "+ Add", testID: "family-add-item", onPress: () => router.push("/finance/family/add-item" as any) }}
                  />
                  <FoldCard testID="family-items">
                    {items.length === 0 ? (
                      <Text style={s.empty}>Entries you add from this phone show here so you can delete them.</Text>
                    ) : items.map((it, i) => (
                      <FoldRow
                        key={it.id}
                        first={i === 0}
                        label={it.name}
                        meta={`${it.side === "asset" ? "Asset" : "Liability"} · ${groupLabel(it.group)} · ${Object.entries(it.shares).map(([id, p]) => `${nameOf(id)} ${p}%`).join(", ")}`}
                        right={
                          <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                            <Text style={{ fontSize: 14, fontWeight: "700", color: financeColors.ink }}>{reportMoney("INR", it.amount)}</Text>
                            <Pressable onPress={() => removeItem(it)} hitSlop={10} disabled={!!busy} testID={`family-item-delete-${it.id}`}>
                              <Ionicons name="trash-outline" size={18} color={financeColors.negative} />
                            </Pressable>
                          </View>
                        }
                        testID={`family-item-${it.id}`}
                      />
                    ))}
                  </FoldCard>
                </View>

                {me ? (
                  <View testID="family-my-sharing">
                    <FoldSectionHeader label="My sharing" hint="What the family sees of your own money" />
                    <View style={s.chipRow}>
                      {SHARE_OPTIONS.map((o) => {
                        const on = (me.share ?? "total") === o.code;
                        return (
                          <Pressable key={o.code} style={[s.chip, on && s.chipOn]} disabled={!!busy || on} onPress={() => run("share", () => api.updateFamilyMe(o.code), "Sharing updated.")} testID={`family-share-${o.code}`}>
                            <Text style={[s.chipText, on && s.chipTextOn]}>{o.label}</Text>
                          </Pressable>
                        );
                      })}
                    </View>
                  </View>
                ) : null}

                <Pressable
                  style={[s.secondary, { borderColor: financeColors.negative }]}
                  disabled={!!busy}
                  onPress={() => confirm("Leave", "Leave this family? Your own money stops showing in the family net worth.", () => run("leave", () => api.leaveFamily(), "You've left the family."))}
                  testID="family-leave"
                >
                  <Text style={[s.secondaryText, { color: financeColors.negative }]}>Leave family</Text>
                </Pressable>
              </>
            )}
          </>
        )}
      </ScrollView>
      <FamilyMemberSheet mode={sheet} onClose={() => setSheet(null)} onDone={(msg) => { setSheet(null); setNotice(msg); load(); }} />
    </SafeAreaView>
  );
}
