import { APP_NAME } from "../config";

/** The version of the Terms and Privacy Policy shown to people. It is sent with every sign-up and the
 *  server records it. Change it, and TERMS_VERSION in the backend settings, to the same value whenever
 *  either document changes. */
export const LEGAL_VERSION = "2026-10-27";
export const LEGAL_UPDATED = "27 October 2026";

/** Who "we" are in the legal pages. Set these in the frontend environment (see .env.example). Anything
 *  left empty is simply not shown, so the pages never display made-up details. */
export const COMPANY = {
  name: import.meta.env.VITE_COMPANY_NAME || APP_NAME,
  email: import.meta.env.VITE_SUPPORT_EMAIL || "",
  address: import.meta.env.VITE_COMPANY_ADDRESS || "",
  dpcRegistration: import.meta.env.VITE_DPC_REGISTRATION || "",
};
