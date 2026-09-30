/** The topbar and the pages each fetch the wallet on their own. When something
 *  changes the balance (a top-up lands, a message is sent), call
 *  notifyWalletChanged() so anything showing it can refetch. */
const EVENT = "portal:wallet-changed";

export function notifyWalletChanged() {
  window.dispatchEvent(new Event(EVENT));
}

/** Subscribe; returns the unsubscribe function. */
export function onWalletChanged(callback) {
  window.addEventListener(EVENT, callback);
  return () => window.removeEventListener(EVENT, callback);
}
