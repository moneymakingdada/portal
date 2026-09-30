const TZ = "Africa/Accra";

const money = new Intl.NumberFormat("en-GH", { style: "currency", currency: "GHS" });
/** 250 pesewas -> "GH₵2.50" */
export const ghs = (pesewas) => money.format((pesewas || 0) / 100);

/** Signed amount for a ledger row: "+GH₵2.00" / "−GH₵0.05" */
export function signedGhs(pesewas) {
  const text = money.format(Math.abs(pesewas || 0) / 100);
  return `${pesewas < 0 ? "\u2212" : "+"}${text}`;
}

const dateTime = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ,
});
export const formatDateTime = (iso) => (iso ? dateTime.format(new Date(iso)) : "—");

const dateOnly = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: TZ });
export const formatDate = (iso) => (iso ? dateOnly.format(new Date(iso)) : "—");

export const number = (n) => new Intl.NumberFormat("en-GB").format(n || 0);

export function pluralize(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    document.body.removeChild(area);
    return ok;
  }
}
