import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Rating } from "../../api/chat";
import { IconButton } from "../../components/Button/IconButton";
import styles from "./AnswerRating.module.css";

const THANKS: Record<Rating, string> = {
  up: "Thanks — glad it helped.",
  down: "Thanks — your feedback helps improve answers.",
};
const FAILED = "Your rating couldn't be saved. Try again.";

// Helpful / Not helpful for one answer (DESIGN.md → Chat). Renders the buttons and, as a sibling that takes a line of its
// own in the flex row it sits in, a visible note. The clicked button shows pressed at once and goes back to the saved
// rating if saving fails. A pressed button doesn't un-press: clicking it saves nothing. `onAnnounce` gets the outcome
// for the page's one polite live region; the note itself is not one.
export function AnswerRating({
  rating,
  onRate,
  onAnnounce,
}: {
  rating: Rating | null;
  onRate: (rating: Rating) => Promise<void>;
  onAnnounce?: (text: string) => void;
}) {
  const [pending, setPending] = useState<Rating | null>(null);
  const [failed, setFailed] = useState(false);
  // Only the latest click may settle the buttons: an older reply that arrives late must not undo a newer rating.
  const latest = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const shown = pending ?? rating;
  const note = failed ? FAILED : shown ? THANKS[shown] : null;

  async function rate(next: Rating) {
    if (next === shown) return;
    const click = ++latest.current;
    setFailed(false);
    setPending(next);
    try {
      await onRate(next);
      if (click === latest.current && mounted.current) onAnnounce?.(THANKS[next]);
    } catch {
      if (click === latest.current && mounted.current) {
        setFailed(true);
        onAnnounce?.(FAILED);
      }
    } finally {
      if (click === latest.current && mounted.current) setPending(null);
    }
  }

  return (
    <>
      <span className={styles.rating}>
        <IconButton label="Helpful" icon={ThumbsUp} aria-pressed={shown === "up"} onClick={() => void rate("up")} />
        <IconButton label="Not helpful" icon={ThumbsDown} aria-pressed={shown === "down"} onClick={() => void rate("down")} />
      </span>
      {note && <span className={styles.note}>{note}</span>}
    </>
  );
}
