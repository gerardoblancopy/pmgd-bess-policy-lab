"use client";

import type { ParamMeta } from "@/lib/api";

export function ParamSlider({
  meta,
  value,
  onChange,
}: {
  meta: ParamMeta;
  value: number;
  onChange: (value: number) => void;
}) {
  const label = meta.label
    .replaceAll("\u2013", "-")
    .replaceAll("\u2014", "-");
  const format = (number: number) =>
    Math.abs(number) >= 10_000
      ? number.toLocaleString("en-US", { maximumFractionDigits: 0 })
      : Number(number.toFixed(4)).toString();

  return (
    <div className="parameter-card">
      <div className="parameter-heading">
        <label htmlFor={meta.name}>
          {label}
          {meta.unit ? <span>{meta.unit}</span> : null}
        </label>
        <input
          className="number-input"
          type="number"
          value={value}
          min={meta.min}
          max={meta.max}
          step={meta.step}
          onChange={(event) => onChange(Number(event.target.value))}
          aria-label={`${label}, numeric value`}
        />
      </div>
      <input
        id={meta.name}
        type="range"
        value={value}
        min={meta.min}
        max={meta.max}
        step={meta.step}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <p className="parameter-range">
        {format(meta.min)} to {format(meta.max)} / paper {format(meta.default)}
      </p>
    </div>
  );
}

export function StatTile({
  label,
  value,
  detail,
  tone = "blue",
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "blue" | "amber" | "ink";
}) {
  return (
    <article className="stat-tile" data-tone={tone}>
      <p>{label}</p>
      <strong>{value}</strong>
      {detail ? <span>{detail}</span> : null}
    </article>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  description: string;
}) {
  return (
    <div className="toggle-row">
      <button
        className="switch"
        type="button"
        role="switch"
        aria-checked={checked}
        data-on={checked}
        onClick={onChange}
      >
        <span className="sr-only">{label}</span>
      </button>
      <div>
        <p>{label}</p>
        <span>{description}</span>
      </div>
    </div>
  );
}

export function DefinitionNote({ children }: { children: React.ReactNode }) {
  return (
    <aside className="definition-note">
      <span aria-hidden="true">i</span>
      <p>{children}</p>
    </aside>
  );
}
