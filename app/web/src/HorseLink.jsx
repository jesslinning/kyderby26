import { getKentuckyDerbyHorseUrl } from "./kentuckyDerbyHorseUrls.js";

export function HorseLink({ name, className }) {
  const url = getKentuckyDerbyHorseUrl(name);
  const combined = [className, "horse-link"].filter(Boolean).join(" ");

  if (!url) {
    return <span className={className || undefined}>{name}</span>;
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className={combined}
    >
      {name}
      <span className="horse-link__sr"> (Kentucky Derby profile, opens in new tab)</span>
    </a>
  );
}
