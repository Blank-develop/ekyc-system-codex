const TIME_ZONE_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

export const localTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Bangkok";

const localOffset =
  new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
    .formatToParts(new Date())
    .find((part) => part.type === "timeZoneName")?.value ?? "UTC+7";

export const localTimeZoneLabel = `${localTimeZone} (${localOffset})`;

function parseApiTimestamp(value: string): Date | null {
  const timestamp = value.trim();
  if (!timestamp) return null;

  // SQLite drops timezone metadata from UTC datetimes. Restore the UTC suffix
  // before asking the browser to convert the timestamp into the user's zone.
  const normalized = TIME_ZONE_SUFFIX.test(timestamp) ? timestamp : `${timestamp}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatLocalTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = parseApiTimestamp(value);
  return parsed?.toLocaleTimeString(undefined, { timeZone: localTimeZone }) ?? "—";
}

export function formatLocalDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = parseApiTimestamp(value);
  return parsed?.toLocaleString(undefined, { timeZone: localTimeZone }) ?? "—";
}

export function formatLocalDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = parseApiTimestamp(value);
  return parsed?.toLocaleDateString(undefined, { timeZone: localTimeZone }) ?? "—";
}
