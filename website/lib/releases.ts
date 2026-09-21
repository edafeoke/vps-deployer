export type Release = {
  version: string;
  date: string;
  title: string;
  summary: string;
};

export const releases: Release[] = [
  {
    version: "0.3.6",
    date: "2026-09-21",
    title: "SSL state ownership",
    summary:
      "Repair root-owned SSL settings during updates, assign future writes to the service user, and keep project pages available when legacy SSL state is unreadable.",
  },
  {
    version: "0.3.5",
    date: "2026-09-21",
    title: "Privileged helper execution",
    summary:
      "Allow the platform service to invoke its restricted sudo helper while keeping NoNewPrivileges enabled for deployed application units.",
  },
  {
    version: "0.3.4",
    date: "2026-09-21",
    title: "GitHub credential ownership",
    summary:
      "Make production GitHub credentials readable by the service, repair existing root-owned files during updates, and show credential errors without crashing the dashboard.",
  },
  {
    version: "0.3.3",
    date: "2026-09-21",
    title: "Update-site correction",
    summary:
      "Keep the shared documentation and update service on OneBitStack while treating each VPS dashboard hostname as independent configuration.",
  },
  {
    version: "0.3.2",
    date: "2026-09-21",
    title: "Dashboard and release polish",
    summary:
      "Accept root dashboard URLs as host input, generate and copy manual GitHub webhook secrets, and publish complete release history.",
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
