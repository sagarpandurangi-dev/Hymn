// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ['dist/*', 'scripts/cmd-guard/vendor/**'],
  },
  {
    files: ['scripts/cmd-guard/**/*.js'],
    languageOptions: {
      globals: {
        __dirname: 'readonly',
      },
    },
  },
]);
