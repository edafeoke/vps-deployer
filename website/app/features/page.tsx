import type { Metadata } from "next";

import { SiteFooter, SiteHeader } from "@/components/SiteShell";

export const metadata: Metadata = { title: "Features" };

const FEATURES = [
  ["GitHub App on your VPS", "Private key and webhook secret stay on the machine. Push events queue a local deploy."],
  ["Safe releases", "A candidate must be healthy before current switches. Failed builds leave the last good release."],
  ["systemd and nginx", "Process apps run as vps-deployer-app-<project>. Domains write vps-deployer-<project>.conf."],
  ["HTTPS", "Let's Encrypt through a whitelist helper. Keys never enter SQLite or logs."],
  ["Rollback", "Restore the previous successful release without deleting newer files."],
  ["Local dashboard", "HTML console on 127.0.0.1:5100 for this VPS only. Not this website."],
];

export default function FeaturesPage() {
  return (
    <>
      <SiteHeader current="/features" />
      <section className="section">
        <h1>Features</h1>
        <p className="lede">
          Everything below runs on your VPS after install. This page is
          documentation, not a product console.
        </p>
      </section>
      <section className="grid">
        {FEATURES.map(([title, body]) => (
          <article className="card" key={title}>
            <h2>{title}</h2>
            <p className="muted">{body}</p>
          </article>
        ))}
      </section>
      <SiteFooter />
    </>
  );
}
