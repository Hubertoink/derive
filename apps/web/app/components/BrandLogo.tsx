import Link from "next/link";

export function BrandLogo({ linked = true }: { linked?: boolean }) {
  const mark = (
    <span className="brand-logo__art" aria-hidden="true">
      <img className="brand-logo__on-light" src="/brand/derive-on-light.png" alt="" />
      <img className="brand-logo__on-dark" src="/brand/derive-on-dark.png" alt="" />
    </span>
  );

  return linked ? <Link className="brand-logo" href="/" aria-label="dérive – Startseite">{mark}</Link> : <span className="brand-logo">{mark}</span>;
}
