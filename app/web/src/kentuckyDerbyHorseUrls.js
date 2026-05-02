/** Normalize horse_name from predictions for lookup (trim, collapse spaces, uppercase). */
export function normalizeHorseName(name) {
  return String(name ?? "")
    .trim()
    .replace(/\s+/g, " ")
    .toUpperCase();
}

/**
 * Official profile pages on kentuckyderby.com.
 * Keys match normalized names as they appear in combined prediction data.
 */
export const KENTUCKY_DERBY_HORSE_URLS = Object.freeze({
  RENEGADE: "https://www.kentuckyderby.com/horses/renegade/",
  ALBUS: "https://www.kentuckyderby.com/horses/albus/",
  INTREPIDO: "https://www.kentuckyderby.com/horses/intrepido/",
  "LITMUS TEST": "https://www.kentuckyderby.com/horses/litmus-test/",
  "RIGHT TO PARTY": "https://www.kentuckyderby.com/horses/right-to-party/",
  COMMANDMENT: "https://www.kentuckyderby.com/horses/commandment/",
  "DANON BOURBON": "https://www.kentuckyderby.com/horses/danon-bourbon/",
  "SO HAPPY": "https://www.kentuckyderby.com/horses/so-happy/",
  "THE PUMA": "https://www.kentuckyderby.com/horses/the-puma/",
  "WONDER DEAN": "https://www.kentuckyderby.com/horses/wonder-dean-jpn/",
  INCREDIBOLT: "https://www.kentuckyderby.com/horses/incredibolt/",
  "CHIEF WALLABEE": "https://www.kentuckyderby.com/horses/chief-wallabee/",
  "SILENT TACTIC": "https://www.kentuckyderby.com/horses/silent-tactic/",
  POTENTE: "https://www.kentuckyderby.com/horses/potente/",
  "EMERGING MARKET": "https://www.kentuckyderby.com/horses/emerging-market/",
  PAVLOVIAN: "https://www.kentuckyderby.com/horses/pavlovian/",
  "SIX SPEED": "https://www.kentuckyderby.com/horses/six-speed/",
  "FURTHER ADO": "https://www.kentuckyderby.com/horses/further-ado/",
  "GOLDEN TEMPO": "https://www.kentuckyderby.com/horses/golden-tempo/",
  FULLEFFORT: "https://www.kentuckyderby.com/horses/fulleffort/",
  "GREAT WHITE": "https://www.kentuckyderby.com/horses/great-white/",
  OCELLI: "https://www.kentuckyderby.com/horses/ocelli/",
  ROBUSTA: "https://www.kentuckyderby.com/horses/robusta/",
});

export function getKentuckyDerbyHorseUrl(horseName) {
  const key = normalizeHorseName(horseName);
  return KENTUCKY_DERBY_HORSE_URLS[key] ?? null;
}
