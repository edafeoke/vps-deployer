import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const website = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = resolve(website, "..");
const version = "0.1.0";
const publicDir = resolve(website, "public");
const releasesDir = resolve(publicDir, "releases");
const installerDir = resolve(publicDir, "installer");
const staging = resolve(website, ".release-staging", `vps-deployer-${version}`);

mkdirSync(releasesDir, { recursive: true });
mkdirSync(installerDir, { recursive: true });
copyFileSync(resolve(root, "installer", "install.sh"), resolve(publicDir, "install.sh"));
copyFileSync(resolve(root, "installer", "lib.sh"), resolve(installerDir, "lib.sh"));
writeFileSync(resolve(releasesDir, "latest.txt"), `${version}\n`);

rmSync(resolve(website, ".release-staging"), { recursive: true, force: true });
mkdirSync(staging, { recursive: true });

const excludes = [
  ".git",
  ".venv",
  ".local",
  ".pytest_cache",
  ".ruff_cache",
  ".ty_cache",
  "website",
  "node_modules",
  "__pycache__",
];

execFileSync(
  "rsync",
  [
    "-a",
    "--delete",
    ...excludes.flatMap((item) => ["--exclude", item]),
    `${root}/`,
    `${staging}/`,
  ],
  { stdio: "inherit" },
);

execFileSync(
  "tar",
  ["-czf", resolve(releasesDir, `vps-deployer-${version}.tar.gz`), `vps-deployer-${version}`],
  { cwd: resolve(website, ".release-staging"), stdio: "inherit" },
);

rmSync(resolve(website, ".release-staging"), { recursive: true, force: true });
console.log(`Prepared installer and vps-deployer-${version}.tar.gz`);
