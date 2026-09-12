import fs from "node:fs";
import path from "node:path";

import matter from "gray-matter";

export type DocGroup = {
  title: string;
  slugs: string[];
};

export const DOC_GROUPS: DocGroup[] = [
  {
    title: "Start",
    slugs: ["getting-started", "requirements", "installation", "first-project"],
  },
  {
    title: "Operate",
    slugs: [
      "github",
      "projects",
      "deployments",
      "domains",
      "ssl",
      "nginx",
      "environment-variables",
      "rollback",
      "logs",
    ],
  },
  {
    title: "Reference",
    slugs: [
      "cli",
      "api",
      "configuration",
      "security",
      "troubleshooting",
      "updating",
      "uninstall",
    ],
  },
];

export type Doc = {
  slug: string;
  title: string;
  summary: string;
  body: string;
};

const DOCS_DIR = path.join(process.cwd(), "content", "docs");

export function allSlugs(): string[] {
  return DOC_GROUPS.flatMap((group) => group.slugs);
}

export function getDoc(slug: string): Doc | null {
  const file = path.join(DOCS_DIR, `${slug}.md`);
  if (!fs.existsSync(file)) {
    return null;
  }
  const parsed = matter(fs.readFileSync(file, "utf8"));
  return {
    slug,
    title: String(parsed.data.title ?? slug),
    summary: String(parsed.data.summary ?? ""),
    body: parsed.content.trim(),
  };
}

export function listDocs(): Doc[] {
  return allSlugs()
    .map((slug) => getDoc(slug))
    .filter((doc): doc is Doc => doc !== null);
}
