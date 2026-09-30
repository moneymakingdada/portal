/** Leave the app for another site (e.g. Paystack's checkout page).
 *  A function of its own so tests can replace it. */
export function redirectTo(url) {
  window.location.assign(url);
}
