import type { Metadata } from "next";
import Link from "next/link";

import { SiteFooter, SiteHeader } from "@/components/SiteShell";
import { currentRelease } from "@/lib/releases";

export const metadata: Metadata = { title: "Releases" };

export default function ReleasesPage() {
  return (
    <>
      <SiteHeader current="/releases" />
      <section className="section">
        <h1>Releases</h1>
        <p className="lede">
          Versioned source archives used by install.sh. The installer downloads
          only HTTPS URLs on this host.
        </p>
      </section>
      <article className="card">
        <p className="stamp">Current</p>
        <h2>{currentRelease.version}</h2>
        <p className="muted">{currentRelease.summary}</p>
        <p>
          <a href={`/releases/vps-deployer-${currentRelease.version}.tar.gz`}>
            vps-deployer-{currentRelease.version}.tar.gz
          </a>
          {" · "}
          <Link href="/changelog">Changelog</Link>
        </p>
      </article>
      <SiteFooter />
    </>
  );
}
