import styles from "./BrandMark.module.css";

type Props = {
  // "sm" labels the tutor's messages in the chat: a 28px mark and the name in the body font.
  size?: "md" | "sm";
};

export function BrandMark({ size = "md" }: Props) {
  return (
    <span className={size === "sm" ? `${styles.brand} ${styles.sm}` : styles.brand}>
      <svg className={styles.logo} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <rect width="32" height="32" rx="8" fill="var(--accent)" />
        <path d="M6.5 10.2c3-.9 6.2-.5 9.5 1.3v11.3c-3.3-1.8-6.5-2.2-9.5-1.3z" fill="none" stroke="var(--on-accent)" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M25.5 10.2c-3-.9-6.2-.5-9.5 1.3v11.3c3.3-1.8 6.5-2.2 9.5-1.3z" fill="none" stroke="var(--on-accent)" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="m18.6 16.4 1.7 1.7 3-3.4" fill="none" stroke="var(--on-accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className={styles.word}>Smart Tutor</span>
    </span>
  );
}
