import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Plate Trail",
  description: "What license plate cameras can reconstruct about a synthetic driver's week",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
