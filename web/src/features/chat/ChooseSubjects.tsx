import { useEffect, useId, useRef, useState } from "react";

import { BrandMark } from "../../components/BrandMark/BrandMark";
import { Button } from "../../components/Button/Button";
import { SubjectChip } from "../../components/SubjectChip/SubjectChip";
import styles from "./ChooseSubjects.module.css";

const MAX_SUBJECTS = 3;

type Subject = { subject_id: string; name: string };

type Props = {
  subjects: Subject[];
  busy: boolean;
  onContinue: (subjectIds: string[]) => void;
};

// Subject detection was unsure (PRD §8 US-3): the tutor asks which of the learner's subjects the question is
// about, and answers it right after the pick. The ids go out in the order the learner picked them.
export function ChooseSubjects({ subjects, busy, onContinue }: Props) {
  const [picked, setPicked] = useState<string[]>([]);
  const titleId = useId();
  const hintId = useId();
  const atMax = picked.length >= MAX_SUBJECTS;
  const section = useRef<HTMLElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const continueButton = useRef<HTMLButtonElement>(null);
  const wasBusy = useRef(busy);

  // The question box is disabled while the thread waits, so focus would drop to the page: it moves to the
  // question the tutor asks, and the keyboard continues from there into the chips.
  useEffect(() => {
    title.current?.focus();
  }, []);

  // A refused Continue leaves the picker in place; focus returns to Continue if it was lost while busy.
  useEffect(() => {
    const doc = section.current?.ownerDocument;
    if (wasBusy.current && !busy && doc && !section.current?.contains(doc.activeElement)) continueButton.current?.focus();
    wasBusy.current = busy;
  }, [busy]);

  function toggle(id: string) {
    setPicked((current) => (current.includes(id) ? current.filter((p) => p !== id) : [...current, id]));
  }

  return (
    <section ref={section} className={styles.message} aria-labelledby={titleId}>
      <BrandMark size="sm" />
      <div className={styles.card}>
        <h2 ref={title} id={titleId} className={styles.title} tabIndex={-1}>
          Which subjects is this about?
        </h2>
        <p id={hintId} className={styles.hint}>
          Pick 1 to 3. I'll answer your question right after.
        </p>
        <div className={styles.chips} role="group" aria-labelledby={titleId} aria-describedby={hintId}>
          {subjects.map((s) => {
            const on = picked.includes(s.subject_id);
            return (
              <SubjectChip
                key={s.subject_id}
                name={s.name}
                hueKey={s.subject_id}
                pressed={on}
                disabled={busy || (atMax && !on)}
                onToggle={() => toggle(s.subject_id)}
              />
            );
          })}
        </div>
        <div>
          <Button ref={continueButton} variant="primary" disabled={busy || picked.length === 0} onClick={() => onContinue(picked)}>
            Continue
          </Button>
        </div>
      </div>
    </section>
  );
}
