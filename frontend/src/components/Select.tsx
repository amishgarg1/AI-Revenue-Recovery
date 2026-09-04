"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";

import { ChevronRightIcon } from "@/components/icons";

/**
 * A dark-themed select.
 *
 * A native `<select>` renders its option list through the operating system,
 * which cannot be themed — on a dark page it drops a white panel with system
 * fonts over the top. So this is a button plus a listbox, with the keyboard
 * behaviour a native select would have given for free: arrows to move, Enter
 * or Space to choose, Escape to cancel, Home and End to jump, and focus
 * returning to the trigger on close.
 */

export interface SelectOption {
  value: string;
  label?: string;
  /** Shown greyed to the right — a count, usually. */
  hint?: string;
}

export default function Select({
  label,
  options,
  value,
  onChange,
  placeholder = "all",
}: {
  label: string;
  options: SelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();

  const selectedIndex = Math.max(
    options.findIndex((o) => o.value === value),
    0,
  );
  const selected = options[selectedIndex];

  const close = useCallback((refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }, []);

  // Seed the highlight at the moment of opening rather than reacting to `open`
  // in an effect — setting state inside an effect body just to mirror other
  // state is a cascading render, and the open action already knows everything
  // it needs.
  const openList = useCallback(() => {
    setActive(selectedIndex);
    setOpen(true);
  }, [selectedIndex]);

  // Pointer-down rather than click: a click that starts inside and ends
  // outside should not close, and vice versa.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    // Let the list paint before moving focus into it.
    const frame = requestAnimationFrame(() => listRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open]);

  function choose(index: number) {
    onChange(options[index].value);
    close();
  }

  function onListKeyDown(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActive((i) => Math.min(i + 1, options.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActive((i) => Math.max(i - 1, 0));
        break;
      case "Home":
        e.preventDefault();
        setActive(0);
        break;
      case "End":
        e.preventDefault();
        setActive(options.length - 1);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        choose(active);
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        setOpen(false);
        break;
    }
  }

  function onTriggerKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openList();
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <span className="block text-[9.5px] uppercase tracking-[0.16em] text-[var(--ink-3)] mb-1.5 font-mono">
        {label}
      </span>

      <button
        ref={triggerRef}
        type="button"
        onClick={() => (open ? close(false) : openList())}
        onKeyDown={onTriggerKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        className={`flex w-full min-w-[150px] items-center justify-between gap-3 rounded-lg border px-3 py-2 text-[12.5px] font-mono transition-colors ${
          open
            ? "border-[var(--treatment)]/60 bg-[var(--surface-raised)]"
            : "border-[var(--line)] bg-[var(--surface)] hover:border-[var(--line-strong)]"
        }`}
      >
        <span
          className={
            value ? "text-[var(--ink)]" : "text-[var(--ink-3)]"
          }
        >
          {selected?.label ?? selected?.value ?? placeholder}
        </span>
        <span
          className={`shrink-0 text-[var(--ink-3)] transition-transform duration-150 ${
            open ? "rotate-[-90deg]" : "rotate-90"
          }`}
        >
          <ChevronRightIcon size={13} />
        </span>
      </button>

      {open && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label={label}
          aria-activedescendant={`${listId}-${active}`}
          tabIndex={-1}
          onKeyDown={onListKeyDown}
          className="absolute z-50 mt-1.5 w-full min-w-[150px] max-h-[280px] overflow-y-auto rounded-lg border border-[var(--line-strong)] bg-[var(--surface-raised)] p-1 shadow-2xl shadow-black/60 focus:outline-none"
        >
          {options.map((option, i) => {
            const isSelected = option.value === value;
            const isActive = i === active;
            return (
              <li
                key={option.value || "__all__"}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={isSelected}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(i)}
                className={`flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-[12.5px] font-mono ${
                  isActive ? "bg-[var(--surface-inset)]" : ""
                }`}
              >
                <span
                  className="w-3 shrink-0 text-center"
                  style={{
                    color: isSelected ? "var(--treatment)" : "transparent",
                  }}
                >
                  ✓
                </span>
                <span
                  className={
                    isSelected ? "text-[var(--ink)]" : "text-[var(--ink-2)]"
                  }
                >
                  {option.label ?? option.value ?? placeholder}
                </span>
                {option.hint && (
                  <span className="ml-auto text-[var(--ink-4)] tnum">
                    {option.hint}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
