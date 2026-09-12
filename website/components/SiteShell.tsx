import Link from "next/link";

import { DOC_GROUPS, getDoc } from "@/lib/docs";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/features", label: "Features" },
  { href: "/pricing", label: "Pricing" },
  { href: "/docs", label: "Docs" },
  { href: "/releases", label: "Releases" },
];

export function SiteHeader({ current }: { current: string }) {
  return (
    <header className="mast">
      <div>
        <p className="stamp">Public site · installer and docs</p>
        <Link className="wordmark" href="/">
          VPS Deployer
        </Link>
      </div>
      <nav className="nav" aria-label="Primary">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={current === item.href ? "page" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="colophon">
      <p>
        This website distributes the installer and documentation. It does not
        register your VPS, store credentials, or run deployments.
      </p>
      <p>
        After install, your VPS keeps working if this site is down.{" "}
        <Link href="/changelog">Changelog</Link>
      </p>
    </footer>
  );
}

export function DocNav({ current }: { current?: string }) {
  return (
    <aside>
      {DOC_GROUPS.map((group) => (
        <section key={group.title}>
          <p className="stamp">{group.title}</p>
          <nav aria-label={group.title}>
            {group.slugs.map((slug) => (
              <Link
                key={slug}
                href={`/docs/${slug}`}
                aria-current={current === slug ? "page" : undefined}
              >
                {getDoc(slug)?.title ?? slug}
              </Link>
            ))}
          </nav>
        </section>
      ))}
    </aside>
  );
}
