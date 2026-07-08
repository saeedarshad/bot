import {
  CalendarDays,
  BarChart3,
  Megaphone,
  Users,
  LifeBuoy,
  MessageSquareText,
  Settings as SettingsIcon,
} from "lucide-react";

// Staff dashboard navigation. `end` marks exact-match routes (the index).
export const STAFF_NAV = [
  { to: "/", label: "Calendar", icon: CalendarDays, end: true, section: "Operations" },
  { to: "/patients", label: "Patients", icon: Users, section: "Operations" },
  { to: "/escalations", label: "Escalations", icon: LifeBuoy, section: "Operations" },
  { to: "/analytics", label: "Analytics", icon: BarChart3, section: "Growth" },
  { to: "/recalls", label: "Recalls", icon: Megaphone, section: "Growth" },
  { to: "/chat", label: "Chat (test)", icon: MessageSquareText, section: "Tools" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, section: "Tools" },
];
