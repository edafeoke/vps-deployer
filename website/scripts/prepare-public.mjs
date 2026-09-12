import { execFileSync } from "node:child_process";
import { copyFileSync, cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function readPackageVersion(pyproject) {
  const match = readFileSync(pyproject, "utf8").match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) {
    throw new Error(`Unable to read version from ${pyproject}`);
  }
  return match[1];
}

const website = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = resolve(website, "..");
const version = readPackageVersion(resolve(root, "pyproject.toml"));
const publicDir = resolve(website, "public");
const releasesDir = resolve(publicDir, "releases");
const installerDir = resolve(publicDir, "installer");
const stagingRoot = resolve(tmpdir(), `vps-deployer-release-${process.pid}`);
const staging = resolve(stagingRoot, `vps-deployer-${version}`);

mkdirSync(releasesDir, { recursive: true });
mkdirSync(installerDir, { recursive: true });
copyFileSync(resolve(root, "installer", "install.sh"), resolve(publicDir, "install.sh"));
copyFileSync(resolve(root, "installer", "lib.sh"), resolve(installerDir, "lib.sh"));
writeFileSync(resolve(releasesDir, "latest.txt"), `${version}\n`);

rmSync(stagingRoot, { recursive: true, force: true });
mkdirSync(staging, { recursive: true });

const excludes = new Set([
  ".git",
  ".venv",
  ".local",
  ".pytest_cache",
  ".ruff_cache",
  ".ty_cache",
  "website",
  "node_modules",
  "__pycache__",
]);

cpSync(root, staging, {
  recursive: true,
  filter: (src) => {
    if (src === root) {
      return true;
    }
    const rel = relative(root, src);
    return !rel.split("/").some((part) => excludes.has(part));
  },
});

execFileSync(
  "tar",
  ["-czf", resolve(releasesDir, `vps-deployer-${version}.tar.gz`), `vps-deployer-${version}`],
  { cwd: stagingRoot, stdio: "inherit" },
);

rmSync(stagingRoot, { recursive: true, force: true });
console.log(`Prepared installer and vps-deployer-${version}.tar.gz`);
