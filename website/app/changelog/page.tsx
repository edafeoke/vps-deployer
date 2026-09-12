import type { Metadata } from "next";

import { SiteFooter, SiteHeader } from "@/components/SiteShell";

export const metadata: Metadata = { title: "Changelog" };

export default function ChangelogPage() {
  return (
    <>
      <SiteHeader current="/changelog" />
      <section className="section">
        <h1>Changelog</h1>
        <article className="card">
          <p className="stamp">0.1.0</p>
          <h2>Initial release</h2>
          <p className="muted">
            Self-hosted installation on your VPS, localhost API and dashboard,
            GitHub App webhooks, deployment engine, systemd app units, nginx
            domains, Let&apos;s Encrypt, and rollback. This website publishes
            docs and install.sh only.
          </p>
        </article>
      </section>
      <SiteFooter />
    </>
  );
}
