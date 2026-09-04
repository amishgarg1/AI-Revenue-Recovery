import type { Metadata } from "next";
import { Inter, Instrument_Serif, JetBrains_Mono } from "next/font/google";

import Nav from "@/components/Nav";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

// Display face, used only at large sizes: page titles and hero figures.
//
// Inter everywhere is the safe choice and reads as unconsidered - it is the
// face every dashboard defaults to. A high-contrast serif against a dark
// instrument panel does the opposite: it says somebody chose this. It is
// deliberately kept away from small text and anything in a column, where its
// contrast works against legibility and mono's tabular figures win.
const display = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "RecoverOS",
  description:
    "Failed-payment recovery with bounded, audited, measured interventions. The LLM never touches a rupee.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} ${mono.variable} ${display.variable} font-sans antialiased`}
      >
        <div className="flex h-screen overflow-hidden">
          <Nav />
          {/*
            overflow-x-clip, not just overflow-y-auto. Setting one axis to a
            non-visible value makes the other compute to auto, so this element
            was a horizontal scroll container by accident - any element that
            reached past the content box slid the entire page sideways. Clip
            rather than hidden: hidden would make this a scroll container for
            both axes and break sticky positioning inside it.

            Wide content - tables, charts, code - scrolls in its own container
            rather than moving the page.
          */}
          <main className="flex-1 overflow-y-auto overflow-x-clip grid-plane">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
