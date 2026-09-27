// Icon font loader. In native dev/prod builds, @react-native-vector-icons
// autolinking installs the .ttf into the app bundle so the icons render
// without any runtime font-loading. In Expo Go and on web, no autolinking
// happens, so we manually register the Ionicons font that ships with the
// @react-native-vector-icons/ionicons package. The postScriptName expected
// by the icon component is "Ionicons".
//
// Usage: const [loaded, error] = useIconFonts();

import { useFonts } from "expo-font";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const IoniconsFont = require("@react-native-vector-icons/ionicons/fonts/Ionicons.ttf");

export const useIconFonts = (): readonly [boolean, Error | null] =>
  useFonts({ Ionicons: IoniconsFont });
