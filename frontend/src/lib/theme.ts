export const colors = {
  surface: "#FBFBF9",
  onSurface: "#1E1E1C",
  surfaceSecondary: "#F4F4F2",
  onSurfaceSecondary: "#5A5A55",
  surfaceTertiary: "#EBEBE9",
  onSurfaceTertiary: "#82827C",
  surfaceInverse: "#1E1E1C",
  onSurfaceInverse: "#FBFBF9",
  brand: "#808B76",
  brandPrimary: "#808B76",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#9DA893",
  brandTertiary: "#E7EAE3",
  onBrandTertiary: "#2D3328",
  success: "#5D7B61",
  warning: "#C58B44",
  error: "#A65646",
  onError: "#FFFFFF",
  border: "#EBEBE9",
  borderStrong: "#D1D1CE",
  divider: "#EBEBE9",
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 };
export const radius = { sm: 6, md: 12, lg: 20, pill: 999 };

export const fonts = {
  // System fallbacks; keeps the app dependency-free while honouring the calm feel.
  display: "Georgia",
  displayBold: "Georgia",
  body: "System",
};

export const GOAL_STATUSES = ["active", "paused", "completed", "abandoned"] as const;
export type GoalStatus = (typeof GOAL_STATUSES)[number];

export const EVENT_TYPES = [
  "Note",
  "Task",
  "Check-in",
  "Meeting",
  "Reflection",
  "Milestone",
];
