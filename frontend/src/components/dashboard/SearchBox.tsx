"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { searchAuthorised, type SearchResults } from "@/lib/api";
import { dashboardHref, screenForLevel } from "@/lib/scope";
import { Icon } from "../ui/Icon";

type Option =
  | { kind: "unit"; key: string; label: string; detail: string; href: string }
  | { kind: "indicator"; key: string; label: string; detail: string; href: string };

const MIN_LENGTH = 2;

/**
 * Header search over authorised organisation units and indicators only. Results come from
 * `GET /search`, which applies geography and programme scope on the server; nothing is filtered
 * or hidden in the browser.
 */
export function SearchBox({
  period,
  comparison,
  orgUnitId,
}: {
  period: string;
  comparison?: string;
  orgUnitId: string;
}) {
  const router = useRouter();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < MIN_LENGTH) {
      setResults(null);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchAuthorised(trimmed, controller.signal)
        .then((next) => {
          setResults(next);
          setFailed(false);
          setActive(0);
        })
        .catch((error: Error) => {
          if (error.name !== "AbortError") {
            setFailed(true);
          }
        });
    }, 220);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  const options: Option[] = [
    ...(results?.org_units ?? []).map((unit) => ({
      kind: "unit" as const,
      key: `unit-${unit.id}`,
      label: unit.name,
      detail: unit.level_type.replaceAll("_", " "),
      href: dashboardHref({ screen: screenForLevel(unit.level_type), orgUnitId: unit.id, period, comparison }),
    })),
    ...(results?.indicators ?? []).map((indicator) => ({
      kind: "indicator" as const,
      key: `indicator-${indicator.code}`,
      label: indicator.name,
      detail: `${indicator.programme} indicator`,
      href: dashboardHref({
        workspace: indicator.module,
        orgUnitId,
        period,
        comparison,
        indicator: indicator.code,
      }),
    })),
  ];
  const showList = open && query.trim().length >= MIN_LENGTH && results !== null;

  function choose(option: Option | undefined) {
    if (!option) {
      return;
    }
    setOpen(false);
    setQuery("");
    router.push(option.href);
  }

  return (
    <div className="search-box">
      <label className="sr-only" htmlFor={`${listId}-input`}>
        Search authorised places and indicators
      </label>
      <Icon name="search" className="search-icon" />
      <input
        ref={inputRef}
        id={`${listId}-input`}
        type="search"
        role="combobox"
        aria-expanded={showList}
        aria-controls={`${listId}-list`}
        aria-autocomplete="list"
        aria-activedescendant={showList && options[active] ? `${listId}-${options[active].key}` : undefined}
        placeholder="Search place or indicator…"
        value={query}
        maxLength={60}
        autoComplete="off"
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((index) => Math.min(index + 1, Math.max(options.length - 1, 0)));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((index) => Math.max(index - 1, 0));
          } else if (event.key === "Enter") {
            event.preventDefault();
            choose(options[active]);
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {showList ? (
        <ul className="search-results" id={`${listId}-list`} role="listbox" aria-label="Search results">
          {options.length ? (
            options.map((option, index) => (
              <li
                key={option.key}
                id={`${listId}-${option.key}`}
                role="option"
                aria-selected={index === active}
                className={index === active ? "search-option active" : "search-option"}
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(option);
                }}
              >
                <Icon name={option.kind === "unit" ? "pin" : "indicator"} size={16} />
                <span className="search-option-label">{option.label}</span>
                <span className="search-option-detail">{option.detail}</span>
              </li>
            ))
          ) : (
            <li className="search-empty" role="option" aria-selected={false} aria-disabled="true">
              {failed ? "Search is unavailable." : "No authorised matches."}
            </li>
          )}
        </ul>
      ) : null}
    </div>
  );
}
