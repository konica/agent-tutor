import { useEffect } from "react";

import type { AuthClient } from "../../auth/authClient";
import { BrandMark } from "../../components/BrandMark/BrandMark";
import { Button } from "../../components/Button/Button";
import styles from "./LandingPage.module.css";

// Brief §9 landing copy, verbatim.
const STEPS = ["Upload your PDFs", "Ask a question", "Check the page it came from"];
const TRUST: [lead: string, rest: string][] = [
  ["Only your documents:", "the tutor never answers from anything else."],
  ["Private to you:", "no one else sees your documents, conversations, or notes."],
  ["", "Every answer cites the document title and page."],
  ["", "A pilot for laptop browsers."],
];

type Props = { signIn: AuthClient["signIn"] };

// The public page at / (brief §6.0, US-1): outside the app shell, text only. Keycloak opens only
// when a button is chosen; both buttons return to the Library (a signed-in visitor goes straight there).
export function LandingPage({ signIn }: Props) {
  useEffect(() => {
    document.title = "Smart Tutor";
  }, []);

  const createAccount = () => void signIn({ register: true, redirectTo: "/library" });
  const logIn = () => void signIn({ redirectTo: "/library" });
  const ctas = (
    <div className={styles.ctas}>
      <Button variant="primary" size="lg" onClick={createAccount}>
        Create an account
      </Button>
      <Button variant="secondary" size="lg" onClick={logIn}>
        Sign in
      </Button>
    </div>
  );

  return (
    <div className={styles.landing}>
      <header className={styles.head}>
        <BrandMark />
        <Button variant="ghost" onClick={logIn}>
          Sign in
        </Button>
      </header>
      <main className={styles.main} id="main-content">
        <section className={styles.hero} aria-labelledby="landing-title">
          <h1 id="landing-title" className={styles.title}>
            <span>Ask your own documents.</span> <span className={styles.accent}>Get answers you can check.</span>
          </h1>
          <p className={styles.sub}>Upload your PDFs. Smart Tutor answers only from them and shows the title and page for every answer.</p>
          {ctas}
          <p className={styles.pilot}>Pilot · laptop browsers only.</p>
        </section>

        <section className={styles.section} aria-labelledby="landing-how">
          <h2 id="landing-how" className={styles.kicker}>
            How it works
          </h2>
          <ol className={styles.steps} aria-labelledby="landing-how">
            {STEPS.map((step, i) => (
              <li key={step}>
                <span className={styles.num} aria-hidden="true">{`0${i + 1}`}</span>
                <span className={styles.step}>{step}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.section}>
          <ul className={styles.trust} aria-label="What you can rely on">
            {TRUST.map(([lead, rest]) => (
              <li key={rest}>
                {lead && <strong>{lead}</strong>}
                {lead && " "}
                {rest}
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.close} aria-labelledby="landing-close">
          <h2 id="landing-close" className={styles.closeTitle}>
            Ask your own documents.
          </h2>
          {ctas}
        </section>
      </main>
      <footer className={styles.foot}>© 2026 Smart Tutor</footer>
    </div>
  );
}
