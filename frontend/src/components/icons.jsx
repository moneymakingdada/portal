const base = {
  width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.75, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true, focusable: "false",
};
const icon = (children) =>
  function Icon(props) {
    return <svg {...base} {...props}>{children}</svg>;
  };

export const IconTag = icon(<><path d="M11.5 3.5H5a1.5 1.5 0 0 0-1.5 1.5v6.5a1.5 1.5 0 0 0 .44 1.06l8 8a1.5 1.5 0 0 0 2.12 0l6.5-6.5a1.5 1.5 0 0 0 0-2.12l-8-8a1.5 1.5 0 0 0-1.06-.44z" /><circle cx="8" cy="8" r="1.4" /></>);
export const IconOverview = icon(<><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>);
export const IconApiKeys = icon(<><circle cx="8" cy="15" r="4" /><path d="M11 12l9-9M16 7l3 3M14 9l2 2" /></>);
export const IconKey = IconApiKeys;
export const IconMessage = icon(<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />);
export const IconWallet = icon(<><path d="M3 7a2 2 0 0 1 2-2h13v4" /><path d="M3 7v11a2 2 0 0 0 2 2h14a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1H5a2 2 0 0 1-2-2z" /><circle cx="16.5" cy="14.5" r="1" /></>);
export const IconBook = icon(<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5V21h16" />);
export const IconLogout = icon(<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5M21 12H9" /></>);
export const IconCopy = icon(<><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></>);
export const IconCheck = icon(<path d="M5 12.5l4.5 4.5L19 7.5" />);
export const IconMenu = icon(<path d="M4 7h16M4 12h16M4 17h16" />);
export const IconClose = icon(<path d="M6 6l12 12M18 6L6 18" />);
export const IconUsers = icon(<><circle cx="9" cy="8" r="3.25" /><path d="M3.5 19c0-3 2.5-5.5 5.5-5.5s5.5 2.5 5.5 5.5" /><path d="M15.5 8.25a2.75 2.75 0 1 1 0 5.5" /><path d="M15.75 13.75c2.4.4 4.25 2.4 4.25 5.25" /></>);
export const IconGift = icon(<><rect x="4" y="10" width="16" height="10" rx="1.5" /><path d="M4 10h16v-1a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2z" /><path d="M12 7v13" /><path d="M12 7c-1.2 0-3-1-3-2.6A1.9 1.9 0 0 1 10.9 2.5C12.4 2.5 12 5 12 7z" /><path d="M12 7c1.2 0 3-1 3-2.6a1.9 1.9 0 0 0-1.9-1.9C11.6 2.5 12 5 12 7z" /></>);
export const IconArrowLeft = icon(<><path d="M19 12H5" /><path d="M11 6l-6 6 6 6" /></>);
export const IconEdit = icon(<><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3" /><path d="M13.5 6.5l3 3" /></>);
export const IconStar = icon(<path d="M12 3.5l2.6 5.3 5.8.85-4.2 4.1 1 5.8-5.2-2.75-5.2 2.75 1-5.8-4.2-4.1 5.8-.85z" />);
export const IconSettings = icon(<><circle cx="12" cy="12" r="3" /><path d="M19.4 13a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V19a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 13a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 7a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 2.6a1.7 1.7 0 0 0 1-1.55V1a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 7a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" /></>);
export const IconCart = icon(<><circle cx="9" cy="20" r="1.5" /><circle cx="18" cy="20" r="1.5" /><path d="M2.5 3.5h2.7l2.3 11.2a1.5 1.5 0 0 0 1.5 1.2h8.4a1.5 1.5 0 0 0 1.5-1.1l1.6-6.1H6.1" /></>);
