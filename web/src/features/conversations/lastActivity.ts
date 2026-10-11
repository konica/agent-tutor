import { APP_TIME_ZONE } from "../../time";

const day = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: APP_TIME_ZONE }); // YYYY-MM-DD in GMT+7
const time = (d: Date) => d.toLocaleTimeString("en-GB", { timeZone: APP_TIME_ZONE, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

// When the learner last asked in a conversation, in the app time zone (PRD D27): "Today, 09:48", "Yesterday, 16:20",
// "30 Sep", or "30 Sep 2025" in another year. GMT+7 has no DST, so "now - 24h" is always yesterday's date there.
export function lastActivity(iso: string, now = new Date()): string {
  const at = new Date(iso);
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  if (day(at) === day(now)) return `Today, ${time(at)}`;
  if (day(at) === day(yesterday)) return `Yesterday, ${time(at)}`;
  const sameYear = day(at).slice(0, 4) === day(now).slice(0, 4);
  // en-GB spells September "Sept" in newer ICU, so the month comes from en-US ("Sep") and is joined by hand.
  const month = at.toLocaleDateString("en-US", { timeZone: APP_TIME_ZONE, month: "short" });
  const date = `${Number(day(at).slice(8))} ${month}`;
  return sameYear ? date : `${date} ${day(at).slice(0, 4)}`;
}
