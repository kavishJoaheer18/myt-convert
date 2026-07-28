import type { Config } from "tailwindcss";

/**
 * Palette and type taken from the myt Core Guidelines v1.0.
 * RGB values are authoritative there; CMYK and Pantone are indicative only.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Primary palette
        telecom: "#0D0A73",
        myt: "#153ED9",
        digital: "#0A6ED2",
        aqua: "#00B4C8",
        "light-grey": "#DCDCDC",
        // Secondary palette, one colour per service
        money: "#64BE64",
        care: "#E65078",
        traffic: "#7850DC",
      },
      fontFamily: {
        // Poppins is the primary brand typeface; Geist Mono is the guidelines'
        // companion for monospaced settings such as cell references.
        sans: ["var(--font-poppins)", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        // The wordmark is built on rounded curves and clean terminals; surfaces
        // echo that rather than using square corners.
        brand: "14px",
      },
      backgroundImage: {
        // "Each service combines Digital Blue with a dedicated secondary
        // colour. Linear gradient 0°."
        "myt-gradient": "linear-gradient(90deg, #0D0A73 0%, #153ED9 55%, #0A6ED2 100%)",
        "aqua-gradient": "linear-gradient(90deg, #0A6ED2 0%, #00B4C8 100%)",
      },
    },
  },
  plugins: [],
};

export default config;
