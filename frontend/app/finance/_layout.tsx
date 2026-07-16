import { Stack } from "expo-router";

export default function FinanceLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="commitments/index" />
      <Stack.Screen name="commitments/new" options={{ presentation: "modal" }} />
      <Stack.Screen name="commitments/[id]" />
      <Stack.Screen name="position/assets" />
      <Stack.Screen name="position/liabilities" />
      <Stack.Screen name="position/net-worth" />
      <Stack.Screen name="position/liquidity" />
      <Stack.Screen name="monthly/index" />
      <Stack.Screen name="monthly-drill" />
      <Stack.Screen name="forecast/index" />
      <Stack.Screen name="forecast-month" />
      <Stack.Screen name="scenarios" />
      <Stack.Screen name="scenarios-index" />
      <Stack.Screen name="scenarios-detail" />
      <Stack.Screen name="expected-income" />
      <Stack.Screen name="reconciliation" />
      <Stack.Screen name="events/index" />
      <Stack.Screen name="events/[id]" />
      <Stack.Screen name="reviews" />
      <Stack.Screen name="audit/[recordType]/[recordId]" />
    </Stack>
  );
}
