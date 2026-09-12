import Link from "next/link";

import { SiteFooter, SiteHeader } from "@/components/SiteShell";

export default function NotFound() {
  return (
    <>
      <SiteHeader current="" />
      <section className="section">
        <h1>Page not found</h1>
        <p className="lede">
          That path is not on this website. Try the{" "}
          <Link href="/docs">documentation index</Link>.
        </p>
      </section>
      <SiteFooter />
    </>
  );
}
