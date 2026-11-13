// Amounts come from the API in paisa (100 paisa = 1 taka).
export function bdt(paisa: number): string {
  const sign = paisa < 0 ? "-" : "";
  const abs = Math.abs(paisa);
  const taka = Math.floor(abs / 100).toLocaleString("en-IN");
  const rest = abs % 100;
  return `${sign}BDT ${taka}${rest ? "." + String(rest).padStart(2, "0") : ""}`;
}

export function monthName(period: string): string {
  const [y, m] = period.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}
