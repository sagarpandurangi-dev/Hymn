import { useCallback, useState } from "react";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/lib/api";
import { colors, fonts, radius, spacing } from "@/src/lib/theme";

type EventItem = {
  id: string;
  type: string;
  title: string;
  date: string;
  time: string;
  notes: string;
};

const todayISO = () => new Date().toISOString().slice(0, 10);

const formatDateHeader = () => {
  const d = new Date();
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
};

function Card({
  testID,
  title,
  icon,
  empty,
  onPress,
  children,
}: {
  testID: string;
  title: string;
  icon: keyof typeof Ionicons.glyphMap;
  empty: string;
  onPress: () => void;
  children?: React.ReactNode;
}) {
  return (
    <Pressable
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}
      onPress={onPress}
      testID={testID}
    >
      <View style={styles.cardHead}>
        <View style={styles.cardHeadLeft}>
          <Ionicons name={icon} size={18} color={colors.brandPrimary} />
          <Text style={styles.cardTitle}>{title}</Text>
        </View>
        <Ionicons name="chevron-forward" size={18} color={colors.onSurfaceTertiary} />
      </View>
      {children ? children : <Text style={styles.cardEmpty}>{empty}</Text>}
    </Pressable>
  );
}

export default function TodayScreen() {
  const router = useRouter();
  const [events, setEvents] = useState<EventItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const all = await api.listEvents();
      const t = todayISO();
      setEvents(all.filter((e) => e.date === t));
    } catch {
      setEvents([]);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brandPrimary} />}
      >
        <Text style={styles.hello} testID="today-date-header">{formatDateHeader()}</Text>
        <Text style={styles.subhead}>Today.</Text>

        <View style={styles.stack}>
          <Card
            testID="card-check-ins"
            title="Required Check-ins"
            icon="checkmark-circle-outline"
            empty="No check-ins scheduled."
            onPress={() => router.push("/check-ins")}
          />
          <Card
            testID="card-upcoming-tasks"
            title="Upcoming Tasks"
            icon="list-outline"
            empty="Nothing on your list yet."
            onPress={() => router.push("/tasks")}
          />
          <Card
            testID="card-todays-events"
            title="Today's Events"
            icon="calendar-outline"
            empty="No events today."
            onPress={() => router.push("/(tabs)/timeline")}
          >
            {events.length > 0 ? (
              <View style={styles.eventsPreview}>
                {events.slice(0, 3).map((e) => (
                  <View key={e.id} style={styles.eventRow}>
                    <Text style={styles.eventTime}>{e.time}</Text>
                    <Text style={styles.eventTitle} numberOfLines={1}>{e.title}</Text>
                  </View>
                ))}
                {events.length > 3 && <Text style={styles.eventMore}>+{events.length - 3} more</Text>}
              </View>
            ) : (
              <Text style={styles.cardEmpty}>No events today.</Text>
            )}
          </Card>
          <Card
            testID="card-todays-spending"
            title="Today's Spending"
            icon="cash-outline"
            empty="Quiet spending today."
            onPress={() => router.push("/spending")}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  scroll: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg, paddingBottom: spacing.xxxl * 2 },
  hello: { fontSize: 14, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  subhead: { fontFamily: fonts.displayBold, fontSize: 36, color: colors.onSurface, fontWeight: "700", marginTop: spacing.xs, marginBottom: spacing.xl },
  stack: { gap: spacing.lg },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
  },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  cardHeadLeft: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  cardTitle: { fontSize: 15, color: colors.onSurface, fontWeight: "600" },
  cardEmpty: { fontSize: 13, color: colors.onSurfaceSecondary, marginTop: spacing.xs },
  eventsPreview: { gap: spacing.sm, marginTop: spacing.xs },
  eventRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  eventTime: { fontSize: 12, color: colors.onSurfaceTertiary, width: 52 },
  eventTitle: { fontSize: 14, color: colors.onSurface, flex: 1 },
  eventMore: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.xs },
});
