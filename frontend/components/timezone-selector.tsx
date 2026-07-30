"use client";

import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type InputHTMLAttributes,
} from "react";
import { Input } from "@/components/ui/input";
import { platformApi } from "@/lib/api";

type IntlWithTimeZones = typeof Intl & {
  supportedValuesOf?: (key: "timeZone") => string[];
};

const TIMEZONE_ALIASES: Record<string, string> = {
  "Asia/Calcutta": "Asia/Kolkata",
  "Etc/UTC": "UTC",
  "Etc/GMT": "UTC",
  GMT: "UTC",
};

export function canonicalTimezone(timezone: string): string {
  return TIMEZONE_ALIASES[timezone] ?? timezone;
}

export function browserTimezone(): string {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  return canonicalTimezone(timezone);
}

export function ianaTimezones(): string[] {
  const supported = (Intl as IntlWithTimeZones).supportedValuesOf?.("timeZone") ?? [];
  return Array.from(
    new Set(["UTC", browserTimezone(), ...supported.map(canonicalTimezone)]),
  ).sort();
}

function matchesTimezone(timezone: string, query: string): boolean {
  const searchable = timezone.replaceAll("_", " ").toLowerCase();
  return searchable.includes(query.trim().replaceAll("_", " ").toLowerCase());
}

export const TimezoneSelector = forwardRef<
  HTMLInputElement,
  Omit<InputHTMLAttributes<HTMLInputElement>, "list">
>(function TimezoneSelector({ onChange, onFocus, onBlur, value, defaultValue, ...props }, forwardedRef) {
  const listId = useId();
  const [timezones, setTimezones] = useState(ianaTimezones);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let active = true;
    platformApi.timezones()
      .then(({ timezones: catalog, aliases }) => {
        if (!active) return;
        const normalized = catalog.map(
          (timezone) => aliases[timezone] ?? canonicalTimezone(timezone),
        );
        setTimezones(Array.from(new Set(normalized)).sort());
      })
      .catch(() => {
        // Keep the browser-provided catalog if the authenticated request fails.
      });
    return () => {
      active = false;
    };
  }, []);

  const filtered = timezones.filter((timezone) => matchesTimezone(timezone, query));
  const selectTimezone = (timezone: string) => {
    const input = inputRef.current;
    if (!input) return;
    const valueSetter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    valueSetter?.call(input, timezone);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    setQuery("");
    setOpen(false);
    input.focus();
  };

  return (
    <div className="relative">
      <Input
        {...props}
        ref={(node) => {
          inputRef.current = node;
          if (typeof forwardedRef === "function") forwardedRef(node);
          else if (forwardedRef) forwardedRef.current = node;
        }}
        role="combobox"
        aria-autocomplete="list"
        aria-controls={listId}
        aria-expanded={open}
        autoComplete="off"
        value={value === undefined ? undefined : canonicalTimezone(String(value))}
        defaultValue={defaultValue === undefined ? undefined : canonicalTimezone(String(defaultValue))}
        onChange={(event: ChangeEvent<HTMLInputElement>) => {
          setQuery(event.target.value);
          setOpen(true);
          onChange?.(event);
        }}
        onFocus={(event) => {
          setQuery("");
          setOpen(true);
          event.currentTarget.select();
          onFocus?.(event);
        }}
        onBlur={(event) => {
          setOpen(false);
          onBlur?.(event);
        }}
      />
      {open && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-md border border-slate-200 bg-white py-1 shadow-lg"
        >
          {filtered.length > 0 ? filtered.map((timezone) => (
            <button
              key={timezone}
              type="button"
              role="option"
              aria-selected={canonicalTimezone(String(value ?? defaultValue ?? "")) === timezone}
              className="block w-full px-3 py-2 text-left text-sm hover:bg-blue-50 focus:bg-blue-50 focus:outline-none"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectTimezone(timezone)}
            >
              {timezone}
            </button>
          )) : (
            <p className="px-3 py-2 text-sm text-slate-500">No matching timezone</p>
          )}
        </div>
      )}
    </div>
  );
});
