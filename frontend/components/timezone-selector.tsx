"use client";

import type { InputHTMLAttributes } from "react";
import { Input } from "@/components/ui/input";

type IntlWithTimeZones = typeof Intl & {
  supportedValuesOf?: (key: "timeZone") => string[];
};

export function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function ianaTimezones(): string[] {
  const supported = (Intl as IntlWithTimeZones).supportedValuesOf?.("timeZone") ?? [];
  return Array.from(new Set(["UTC", browserTimezone(), ...supported])).sort();
}

export function TimezoneSelector(
  props: Omit<InputHTMLAttributes<HTMLInputElement>, "list">,
) {
  const timezones = ianaTimezones();
  return (
    <>
      <Input {...props} list="iana-timezones" autoComplete="off" />
      <datalist id="iana-timezones">
        {timezones.map((timezone) => (
          <option key={timezone} value={timezone} />
        ))}
      </datalist>
    </>
  );
}
