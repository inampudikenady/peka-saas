export function formatDateTime(
  value: string | Date,
  timeZone = "UTC",
): string {
  const options: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
    timeZoneName: "short",
  };
  try {
    return new Intl.DateTimeFormat(undefined, options).format(
      typeof value === "string" ? new Date(value) : value,
    );
  } catch {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone: "UTC" }).format(
      typeof value === "string" ? new Date(value) : value,
    );
  }
}

export function formatDate(value: string | Date, timeZone = "UTC"): string {
  const options: Intl.DateTimeFormatOptions = {
    dateStyle: "medium",
    timeZone,
  };
  try {
    return new Intl.DateTimeFormat(undefined, options).format(
      typeof value === "string" ? new Date(value) : value,
    );
  } catch {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone: "UTC" }).format(
      typeof value === "string" ? new Date(value) : value,
    );
  }
}
