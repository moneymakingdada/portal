import { Link } from "react-router-dom";
import { APP_NAME } from "../config";

export function LogoMark({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" fill="#0b2f26" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="7.5" fill="none" stroke="#ecdcae" strokeOpacity="0.28" />
      <rect x="8" y="14" width="4" height="10" rx="2" fill="#c9a24a" />
      <rect x="14" y="8" width="4" height="16" rx="2" fill="#c9a24a" />
      <rect x="20" y="11" width="4" height="13" rx="2" fill="#c9a24a" />
    </svg>
  );
}

export default function Logo({ to = "/", light = false }) {
  return (
    <Link to={to} className={`logo${light ? " logo--light" : ""}`} aria-label={`${APP_NAME} home`}>
      <LogoMark />
      <span className="logo__word">{APP_NAME}</span>
    </Link>
  );
}
