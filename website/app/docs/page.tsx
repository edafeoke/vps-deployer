import type { Metadata } from "next";
import Link from "next/link";

import { SiteFooter, SiteHeader } from "@/components/SiteShell";
import { DOC_GROUPS, getDoc } from "@/lib/docs";

export const metadata: Metadata = { title: "Docs" };

export default function DocsIndexPage() {
  return (
    <>
      <SiteHeader current="/docs" />
      <section className="section">
        <h1>Documentation</h1>
        <p className="lede">
          Guides for the VPS installation. The local dashboard at
          127.0.0.1:5100 is a different system from this website.
        </p>
      </section>
      {DOC_GROUPS.map((group) => (
        <section className="section" key={group.title}>
          <h2>{group.title}</h2>
          <div className="grid">
            {group.slugs.map((slug) => {
              const doc = getDoc(slug);
              return (
                <article className="card" key={slug}>
                  <h2>
                    <Link href={`/docs/${slug}`}>{doc?.title ?? slug}</Link>
                  </h2>
                  <p className="muted">{doc?.summary}</p>
                </article>
              );
            })}
          </div>
        </section>
      ))}
      <SiteFooter />
    </>
  );
}
