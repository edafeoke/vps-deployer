import type { Metadata } from "next";

import { SiteFooter, SiteHeader } from "@/components/SiteShell";

export const metadata: Metadata = { title: "Pricing" };

export default function PricingPage() {
  return (
    <>
      <SiteHeader current="/pricing" />
      <section className="section">
        <h1>Pricing</h1>
        <p className="lede">
          VPS Deployer is software you install. There is no seat license and no
          per-deploy fee collected by this website.
        </p>
      </section>
      <section className="price">
        <article className="card">
          <p className="stamp">Installer</p>
          <h2>No account charge</h2>
          <p className="muted">
            Download and run install.sh. You do not pay this site to create a
            project or queue a deployment.
          </p>
        </article>
        <article className="card">
          <p className="stamp">Your infrastructure</p>
          <h2>You pay your VPS</h2>
          <p className="muted">
            CPU, disk, bandwidth, and domains are billed by your VPS and DNS
            providers. GitHub and Let&apos;s Encrypt remain their own services.
          </p>
        </article>
      </section>
      <SiteFooter />
    </>
  );
}
