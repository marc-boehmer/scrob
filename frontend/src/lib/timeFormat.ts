export function use24HourTime(accountPreference: boolean | null | undefined, cookieValue?: string): boolean {
  return accountPreference ?? cookieValue === "true";
}
