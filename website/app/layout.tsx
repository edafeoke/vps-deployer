import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono } from "next/font/google";

import "./globals.css";

const display = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: {
    default: "VPS Deployer",
    template: "%s · VPS Deployer",
  },
  description:
    "Self-hosted deployment platform you install on your VPS. This website is docs and the installer only.",
  metadataBase: new URL("https://vps-deployer.onebitstack.com"),
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${mono.variable}`}>
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <div className="shell">
          <main id="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
