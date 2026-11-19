import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useLocalSearchParams } from "expo-router";

import { api, ApiError } from "@/src/lib/api";
import FinanceHeader from "@/src/components/finance/FinanceHeader";
import { FoldCard, FoldRow, FoldSectionHeader, foldPageStyle } from "@/src/components/finance/foldUi";
import { lifeStyles as s, perUnitText, PremiumCard } from "@/src/components/finance/lifeObjects";
import { dateLabel } from "@/src/lib/finance/format";
import { financeColors } from "@/src/lib/finance/theme";

const fmt = (v: any, d = 1) => (v == null ? "—" : Number.isFinite(Number(v)) ? Number(v).toFixed(d) : String(v));
const day = (v: any) => (v ? dateLabel(String(v).slice(0, 10)) : "");

export default function FuelScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [data, setData] = useState<any>(null);
  const [premium, setPremium] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getLifeObjectFuel(String(id)).then(setData).catch((e: ApiError) => {
      if (e.status === 403) setPremium(false);
      else setError(e.message || "Couldn't load fuel.");
    });
  }, [id]);

  const cur = data?.currency ?? "INR";
  const stretches: any[] = data?.stretches ?? [];

  return (
    <SafeAreaView style={foldPageStyle} edges={["bottom"]}>
      <FinanceHeader title="Fuel" subtitle="From full-tank check-ins" />
      <ScrollView contentContainerStyle={s.scroll}>
        {!premium ? <PremiumCard text="Fuel tracking is part of Premium." /> : !data ? (
          error ? <Text style={s.error}>{error}</Text> : <ActivityIndicator color={financeColors.inkMuted} />
        ) : (
          <>
            <FoldCard>
              <FoldRow first label="Km per litre" right={fmt(data.km_per_litre)} testID="fuel-kmpl" />
              <FoldRow label="Cost per km" right={data.cost_per_km != null ? perUnitText(cur, { per_unit: data.cost_per_km, unit: "km" }) : "—"} testID="fuel-cost-per-km" />
            </FoldCard>
            <FoldSectionHeader label="Stretches" hint="Between two full tanks" />
            <FoldCard testID="fuel-stretches">
              {stretches.length === 0 ? (
                <Text style={s.empty}>Log two full-tank check-ins with the odometer reading to see your mileage.</Text>
              ) : stretches.map((x, i) => (
                <FoldRow
                  key={i}
                  first={i === 0}
                  label={[day(x.from ?? x.start_date ?? x.from_date), day(x.to ?? x.end_date ?? x.to_date)].filter(Boolean).join(" → ") || `Stretch ${i + 1}`}
                  meta={[x.km != null ? `${fmt(x.km, 0)} km` : "", x.litres != null ? `${fmt(x.litres, 2)} L` : ""].filter(Boolean).join(" · ")}
                  right={x.km_per_litre != null ? `${fmt(x.km_per_litre)} km/L` : undefined}
                  testID={`fuel-stretch-${i}`}
                />
              ))}
            </FoldCard>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
