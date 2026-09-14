import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: "#06345a",
          dark: "#04243f",
          mid: "#0a4a7a",
        },
        canvas: "#f5fbff",
        line: "#d7e8f5",
      },
    },
  },
  plugins: [],
};

export default config;
