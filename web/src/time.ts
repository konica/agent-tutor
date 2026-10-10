// The app time zone (PRD D27): upload days are shown and filtered in it.
export const APP_TIME_ZONE = "Asia/Ho_Chi_Minh";

// When a limit ends, as the Library shows it: "11:40 (GMT+7)" (PRD D27).
export function limitTime(at: Date): string {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: APP_TIME_ZONE, hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "shortOffset" }).formatToParts(at);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("hour")}:${part("minute")} (${part("timeZoneName")})`;
}
