import type { Metadata } from "next";

import { SiteFooter, SiteHeader } from "@/components/SiteShell";
import { releases } from "@/lib/releases";

export const metadata: Metadata = { title: "Changelog" };

export default function ChangelogPage() {
  return (
    <>
      <SiteHeader current="/changelog" />
      <section className="section">
        <h1>Changelog</h1>
        <div className="release-list">
          {releases.map((release) => (
            <article className="card" key={release.version}>
              <p className="stamp">
                {release.version} · {release.date}
              </p>
              <h2>{release.title}</h2>
              <p className="muted">{release.summary}</p>
            </article>
          ))}
        </div>
      </section>
      <SiteFooter />
    </>
  );
}
