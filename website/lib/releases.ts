export type Release = {
  version: string;
  date: string;
  title: string;
  summary: string;
};

export const releases: Release[] = [
  {
    version: "0.3.2",
    date: "2026-09-21",
    title: "Dashboard and release polish",
    summary:
      "Accept root dashboard URLs as host input, generate and copy manual GitHub webhook secrets, publish complete release history, and use the CentralStack public URL.",
  },
  {
    version: "0.3.1",
    date: "2026-09-21",
    title: "Safer updates",
    summary:
      "Skip APT during updates when dependencies are present, improve broken repository diagnostics, and warn when Ubuntu is not an LTS release.",
  },
  {
    version: "0.3.0",
    date: "2026-09-21",
    title: "One-click GitHub connection",
    summary:
      "Add the GitHub App Manifest flow, automatic webhook credentials and repository installation, plus explicit deployment errors when GitHub authentication fails.",
  },
  {
    version: "0.2.0",
    date: "2026-09-12",
    title: "Operations and dashboard settings",
    summary:
      "Add update and uninstall commands, public dashboard controls, and GitHub App configuration and repository visibility.",
  },
  {
    version: "0.1.0",
    date: "2026-09-12",
    title: "Initial release",
    summary:
      "Self-hosted installation, localhost API and dashboard, GitHub webhooks, deployment engine, systemd app units, nginx domains, HTTPS, and rollback.",
  },
];

export const currentRelease = releases[0];
