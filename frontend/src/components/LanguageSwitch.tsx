import { setLang, useLang, type Lang } from "../lib/i18n";

const OPTIONS: Array<{ value: Lang; label: string; name: string }> = [
  { value: "lo", label: "ລາວ", name: "ພາສາລາວ" },
  { value: "en", label: "EN", name: "English" }
];

export function LanguageSwitch() {
  const lang = useLang();
  return (
    <div className="lang-switch" role="group" aria-label="Language / ພາສາ">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          lang={option.value}
          aria-label={option.name}
          aria-pressed={lang === option.value}
          className={lang === option.value ? "active" : ""}
          onClick={() => setLang(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
