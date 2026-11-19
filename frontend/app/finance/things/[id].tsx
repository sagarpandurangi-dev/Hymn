import { useCallback, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import DateTimeField from "@/src/components/DateTimeField";
import { FoldCard, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { entryText, reportMoney, StatementLine } from "@/src/components/finance/ReportBits";
import { curOf, isLoan, isVehicle, kindLabel, lifeStyles as s, perUnitText, PremiumCard, typeLabel } from "@/src/components/finance/lifeObjects";
import { dateLabel, todayIso } from "@/src/lib/finance/format";
import { financeColors, financeSpace } from "@/src/lib/finance/theme";

const amt = (x: any) => (x && typeof x === "object" ? x.amount ?? x.total ?? x.value : x);

export default function ThingDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [obj, setObj] = useState<any>(null);
  const [premium, setPremium] = useState(true);
  const [error, setError] = useState("");
  const [endOpen, setEndOpen] = useState(false);
  const [endedOn, setEndedOn] = useState(todayIso());
  const [soldFor, setSoldFor] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setObj(await api.getLifeObject(String(id)));
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 403) setPremium(false);
      else setError(err.message || "Couldn't load this.");
    }
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const markEnded = async () => {
    setBusy(true);
    setError("");
    try {
      await api.updateLifeObject(String(id), { ended_on: endedOn, sold_for: soldFor || null });
      setEndOpen(false);
      await load();
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 403) setPremium(false);
      else setError(err.message || "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (!premium) {
    return (
      <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
        <FinanceHeader title="Things I own & owe" />
        <View style={s.scroll}><PremiumCard text="Seeing the lifetime cost of what you own and owe is part of Premium." /></View>
      </SafeAreaView>
    );
  }
  if (!obj) {
    return (
      <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
        <FinanceHeader title="Things I own & owe" />
        <View style={s.center}>{error ? <Text style={s.error}>{error}</Text> : <ActivityIndicator color={financeColors.inkMuted} />}</View>
      </SafeAreaView>
    );
  }

  const cur = curOf(obj);
  const ltc = obj.ltc ?? {};
  const b = ltc.breakdown ?? ltc;
  const keeping: any[] = Array.isArray(b.keeping_it) ? b.keeping_it : [];
  const entries: any[] = obj.entries ?? obj.ltc?.entries ?? [];
  const projected = ltc.projected ?? ltc.projected_lifetime ?? ltc.over_life ?? obj.projected;
  const hours = ltc.hours ?? obj.hours;
  const m = (v: any) => reportMoney(cur, amt(v) ?? 0);

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]} testID="thing-detail">
      <FinanceHeader title={obj.name} subtitle={[typeLabel(obj.type), kindLabel(obj.kind), obj.started_on ? `since ${dateLabel(obj.started_on)}` : ""].filter(Boolean).join(" · ")} />
      <ScrollView contentContainerStyle={s.scroll}>
        {obj.ended_on ? (
          <FoldCard><Text style={s.empty} testID="thing-ended">Ended {dateLabel(obj.ended_on)}{obj.sold_for != null ? ` · sold for ${m(obj.sold_for)}` : ""}</Text></FoldCard>
        ) : null}

        <View>
          <FoldSectionHeader label="Lifetime cost to date" />
          <FoldCard testID="thing-ltc">
            <View style={s.pad}>
              <Text style={{ fontSize: 28, fontWeight: "700", color: financeColors.ink }} testID="thing-ltc-to-date">{m(ltc.to_date)}</Text>
            </View>
            <StatementLine label="Getting it" amounts={[m(b.getting_it)]} topRule />
            <StatementLine label="Value lost" amounts={[m(b.value_lost)]} />
            <StatementLine label="Keeping it" amounts={[m(keeping.length ? keeping.reduce((t, k) => t + Number(amt(k) ?? 0), 0) : b.keeping_it_total ?? 0)]} />
            {keeping.map((k, i) => (
              <StatementLine key={i} label={String(k.label ?? k.name ?? k.category ?? "Running cost")} amounts={[m(k)]} indent muted testID={`thing-keeping-${i}`} />
            ))}
            <StatementLine label="Cost of money" amounts={[m(b.cost_of_money)]} />
            <StatementLine label="Came back" amounts={[`−${m(b.came_back)}`]} />
            <StatementLine label="Total" amounts={[m(ltc.to_date)]} bold doubleRule />
          </FoldCard>
        </View>

        <FoldCard>
          <FoldRow first label="Per month" right={m(ltc.per_month)} testID="thing-per-month" />
          {ltc.per_unit != null ? <FoldRow label="Per unit" right={perUnitText(cur, ltc)} testID="thing-per-unit" /> : null}
          {projected != null ? <FoldRow label="Projected over its life" right={m(projected)} testID="thing-projected" /> : null}
          {hours != null ? <FoldRow label="Hours" right={`${Number(hours).toLocaleString()} h`} testID="thing-hours" /> : null}
        </FoldCard>

        <View style={{ gap: financeSpace.sm }}>
          {isLoan(obj) ? (
            <Pressable style={s.secondary} onPress={() => router.push(`/finance/things/schedule?id=${id}` as any)} testID="thing-open-schedule">
              <Ionicons name="calendar-outline" size={18} color={financeColors.ink} />
              <Text style={s.secondaryText}>Loan schedule</Text>
            </Pressable>
          ) : null}
          {isVehicle(obj) ? (
            <Pressable style={s.secondary} onPress={() => router.push(`/finance/things/fuel?id=${id}` as any)} testID="thing-open-fuel">
              <Ionicons name="speedometer-outline" size={18} color={financeColors.ink} />
              <Text style={s.secondaryText}>Fuel</Text>
            </Pressable>
          ) : null}
          {!obj.ended_on ? (
            <Pressable style={s.secondary} onPress={() => setEndOpen(true)} testID="thing-mark-ended">
              <Ionicons name="flag-outline" size={18} color={financeColors.ink} />
              <Text style={s.secondaryText}>Mark sold / ended</Text>
            </Pressable>
          ) : null}
        </View>

        <View>
          <FoldSectionHeader label="Entries" />
          <FoldCard testID="thing-entries">
            {entries.length === 0 ? (
              <Text style={s.empty}>No entries yet.</Text>
            ) : entries.map((e, i) => (
              <FoldRow
                key={String(e.id ?? i)}
                first={i === 0}
                label={entryText(e)}
                meta={[e.date ?? e.event_date ? dateLabel(String(e.date ?? e.event_date).slice(0, 10)) : "", e.category ?? e.bucket ?? ""].filter(Boolean).join(" · ")}
                right={m(e.amount)}
                testID={`thing-entry-${i}`}
              />
            ))}
          </FoldCard>
        </View>
        {error ? <Text style={s.error}>{error}</Text> : null}
      </ScrollView>

      <Modal visible={endOpen} transparent animationType="slide" onRequestClose={() => setEndOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.35)" }}>
          <Pressable style={{ flex: 1 }} onPress={() => setEndOpen(false)} />
          <View style={{ backgroundColor: financeColors.page, padding: financeSpace.xl, borderTopLeftRadius: 16, borderTopRightRadius: 16, gap: financeSpace.sm }}>
            <Text style={s.h}>Mark sold / ended</Text>
            <Text style={s.label}>Ended on</Text>
            <DateTimeField mode="date" value={endedOn} onChange={setEndedOn} testID="thing-ended-on" />
            <Text style={s.label}>Sold for (optional)</Text>
            <TextInput style={s.input} value={soldFor} onChangeText={(v) => setSoldFor(v.replace(/[^0-9.]/g, ""))} keyboardType="decimal-pad" placeholder="0" placeholderTextColor={financeColors.inkMuted} testID="thing-sold-for" />
            {error ? <Text style={s.error}>{error}</Text> : null}
            <Pressable style={[s.primary, { marginTop: 12 }, busy && { opacity: 0.5 }]} onPress={markEnded} disabled={busy || !endedOn} testID="thing-ended-save">
              {busy ? <ActivityIndicator color={financeColors.card} /> : <Text style={s.primaryText}>Save</Text>}
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}
