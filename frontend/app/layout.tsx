import type { Metadata } from "next";
import { Big_Shoulders, Overpass, Overpass_Mono } from "next/font/google";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

// Overpass is an open interpretation of Highway Gothic, the lettering on US road signs.
const body = Overpass({ subsets: ["latin"], variable: "--font-body" });
const mono = Overpass_Mono({ subsets: ["latin"], variable: "--font-mono" });
const display = Big_Shoulders({ subsets: ["latin"], variable: "--font-display" });

export const metadata: Metadata = {
  title: "Plate Trail",
  description: "A location-privacy check-up: public fixed sensors in any area and along the routes you drive",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${body.variable} ${mono.variable} ${display.variable}`}>
      <body>{children}</body>
    </html>
  );
}
