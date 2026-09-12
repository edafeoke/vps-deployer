import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Markdown } from "@/components/Markdown";
import { DocNav, SiteFooter, SiteHeader } from "@/components/SiteShell";
import { allSlugs, getDoc } from "@/lib/docs";

type Props = { params: Promise<{ slug: string }> };

export function generateStaticParams() {
  return allSlugs().map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) {
    return { title: "Not found" };
  }
  return { title: doc.title, description: doc.summary };
}

export default async function DocPage({ params }: Props) {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) {
    notFound();
  }
  return (
    <>
      <SiteHeader current="/docs" />
      <div className="doc-layout">
        <DocNav current={slug} />
        <article>
          <p className="stamp">Docs</p>
          <Markdown source={`# ${doc.title}\n\n${doc.body}`} />
        </article>
      </div>
      <SiteFooter />
    </>
  );
}
