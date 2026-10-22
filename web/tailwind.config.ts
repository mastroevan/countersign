import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        amazon: {
          orange: "#FF9900",
          hover: "#E47911",
          dark: "#131921",
          light: "#232F3E",
        },
      },
    },
  },
  plugins: [],
};

export default config;
