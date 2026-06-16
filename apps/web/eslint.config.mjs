import boundaries from "eslint-plugin-boundaries";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const fsdLayers = ["app", "screens", "widgets", "features", "entities", "shared"];
const fsdSliceTypes = ["screens", "widgets", "features", "entities"];

/** @type {import("eslint").Linter.Config[]} */
const config = [
  ...nextCoreWebVitals,
  {
    plugins: { boundaries },
    settings: {
      "boundaries/root-path": import.meta.dirname,
      "boundaries/elements": [
        { type: "shared", pattern: "src/shared/*", mode: "folder", capture: ["slice"] },
        { type: "entities", pattern: "src/entities/*", mode: "folder", capture: ["slice"] },
        { type: "features", pattern: "src/features/*", mode: "folder", capture: ["slice"] },
        { type: "widgets", pattern: "src/widgets/*", mode: "folder", capture: ["slice"] },
        { type: "screens", pattern: "src/screens/*", mode: "folder", capture: ["slice"] },
        { type: "app", pattern: "src/app", mode: "folder" },
      ],
      "import/resolver": {
        typescript: {
          alwaysTryTypes: true,
          project: "./tsconfig.json",
        },
      },
    },
    rules: {
      "boundaries/dependencies": [
        "error",
        {
          default: "disallow",
          message:
            "{{from.type}} cannot import {{to.type}} (FSD: import only downward; app store is an exception)",
          rules: [
            { from: { type: "app" }, allow: { to: { type: fsdLayers } } },
            {
              from: { type: "screens" },
              allow: { to: { type: ["widgets", "features", "entities", "shared", "app"] } },
            },
            {
              from: { type: "widgets" },
              allow: { to: { type: ["features", "entities", "shared", "app"] } },
            },
            {
              from: { type: "features" },
              allow: { to: { type: ["entities", "shared", "app"] } },
            },
            { from: { type: "entities" }, allow: { to: { type: ["shared", "app"] } } },
            { from: { type: "shared" }, allow: { to: { type: "shared" } } },
            { from: { type: "screens" }, allow: { to: { type: "screens" } } },
            { from: { type: "widgets" }, allow: { to: { type: "widgets" } } },
            { from: { type: "features" }, allow: { to: { type: "features" } } },
            { from: { type: "entities" }, allow: { to: { type: "entities" } } },
            { allow: { dependency: { relationship: { to: "internal" } } } },
            {
              from: { captured: { slice: "{{to.captured.slice}}" } },
              allow: { to: { type: fsdSliceTypes } },
            },
          ],
        },
      ],
      "boundaries/no-unknown": "off",
      "boundaries/no-unknown-files": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: [
      "src/app/model/store/composer-store.tsx",
      "src/widgets/composer/**/*.{ts,tsx}",
      "src/widgets/chat-thread/**/*.{ts,tsx}",
      "src/widgets/note-editor/**/*.{ts,tsx}",
      "src/widgets/charts/**/*.{ts,tsx}",
      "src/widgets/analytics-dashboard/**/*.{ts,tsx}",
      "src/screens/analytics/**/*.{ts,tsx}",
      "src/screens/note/**/*.{ts,tsx}",
      "src/shared/ui/model-picker/**/*.{ts,tsx}",
    ],
    rules: {
      "react-hooks/refs": "off",
      "react-hooks/immutability": "off",
    },
  },
];

export default config;
