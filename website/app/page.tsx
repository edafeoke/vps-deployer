import { CopyCommand } from "@/components/CopyCommand";
import { SiteFooter, SiteHeader } from "@/components/SiteShell";

const INSTALL =
  "curl -fsSL https://vps-deployer.centralstackhq.com/install.sh | sudo bash";

export default function HomePage() {
  return (
    <>
      <SiteHeader current="/" />
      <section className="hero">
        <div>
          <h1>The platform lives on your VPS.</h1>
          <p className="lede">
            Install VPS Deployer once. That machine deploys your applications
            with GitHub, systemd, nginx, HTTPS, logs, and rollback. This website
            does not manage your VPS.
          </p>
        </div>
        <CopyCommand command={INSTALL} />
      </section>
      <section className="grid section">
        <article className="card">
          <h2>No account</h2>
          <p className="muted">
            You do not create an account here to install or deploy. Review the
            installer, then run it as root on your VPS.
          </p>
        </article>
        <article className="card">
          <h2>This VPS only</h2>
          <p className="muted">
            Projects, credentials, and history stay on the machine you
            installed. There is no fleet view and no remote agent.
          </p>
        </article>
        <article className="card">
          <h2>Works offline from us</h2>
          <p className="muted">
            If this site is down, your installation still deploys, rolls back,
            and serves your apps. You only need the internet for GitHub, DNS,
            certificates, and updates.
          </p>
        </article>
      </section>
      <SiteFooter />
    </>
  );
}
