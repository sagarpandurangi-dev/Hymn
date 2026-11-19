import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, FoldRow, foldPageStyle } from "@/src/components/finance/foldUi";
import { reportMoney } from "@/src/components/finance/ReportBits";
import { curOf, kindLabel, lifeStyles as s, objectsOf, perUnitText, PremiumCard, typeLabel } from "@/src/components/finance/lifeObjects";
import { financeColors } from "@/src/lib/finance/theme";

export default function ThingsScreen() {
  const router = useRouter();
  const [items, setItems] = useState<any[] | null>(null);
  const [premium, setPremium] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(objectsOf(await api.listLifeObjects()));
      setError("");
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 403) setPremium(false);
      else setError(err.message || "Couldn't load your things.");
      setItems([]);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]} testID="things-screen">
      <FinanceHeader
        title="Things I own & owe"
        subtitle="What each one really costs you"
        right={premium ? (
          <Pressable onPress={() => router.push("/finance/things/new" as any)} hitSlop={12} testID="things-add">
            <Text style={{ color: financeColors.accent, fontWeight: "700", fontSize: 14 }}>+ Add</Text>
          </Pressable>
        ) : undefined}
      />
      <ScrollView
        contentContainerStyle={s.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        {!premium ? (
          <PremiumCard text="Seeing the lifetime cost of what you own and owe is part of Premium." />
        ) : items === null ? (
          <ActivityIndicator color={financeColors.inkMuted} />
        ) : (
          <>
            {error ? <Text style={s.error}>{error}</Text> : null}
            <FoldCard>
              {items.length === 0 ? (
                <Text style={s.empty}>Nothing here yet. Add your car, home, phone, a loan or a business.</Text>
              ) : (
                items.map((o, i) => {
                  const cur = curOf(o);
                  const ltc = o.ltc ?? {};
                  const meta = [
                    [typeLabel(o.type), kindLabel(o.kind)].filter(Boolean).join(" · "),
                    ltc.per_month != null ? `${reportMoney(cur, ltc.per_month)} a month` : "",
                    perUnitText(cur, ltc),
                    o.ended_on ? "Ended" : "",
                  ].filter(Boolean).join(" · ");
                  return (
                    <FoldRow
                      key={String(o.id ?? i)}
                      first={i === 0}
                      label={o.name}
                      meta={meta}
                      right={<View style={{ alignItems: "flex-end" }}>
                        <Text style={{ fontSize: 15, fontWeight: "700", color: financeColors.ink }}>{reportMoney(cur, ltc.to_date ?? 0)}</Text>
                        <Text style={{ fontSize: 11, color: financeColors.inkMuted }}>so far</Text>
                      </View>}
                      onPress={() => router.push(`/finance/things/${o.id}` as any)}
                      chevron
                      testID={`things-row-${o.id ?? i}`}
                    />
                  );
                })
              )}
            </FoldCard>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
