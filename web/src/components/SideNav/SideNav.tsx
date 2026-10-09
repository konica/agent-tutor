import { ChevronLeft, ChevronRight } from "lucide-react";
import { Fragment } from "react";
import { Link, NavLink } from "react-router";

import { NAV, type RecentConversation } from "../../app/nav";
import { useSession } from "../../auth/SessionProvider";
import { BrandMark } from "../BrandMark/BrandMark";
import { IconButton } from "../Button/IconButton";
import { UserMenu } from "../UserMenu/UserMenu";
import styles from "./SideNav.module.css";

type Props = { collapsed: boolean; onToggle: () => void; recent?: RecentConversation[] };

const GROUPS = [0, 1, 2] as const;

export function SideNav({ collapsed, onToggle, recent = [] }: Props) {
  const { name, signOut } = useSession();
  return (
    <nav className={`${styles.sidenav} ${collapsed ? styles.collapsed : ""}`} aria-label="Main">
      <Link className={styles.brand} to="/library" aria-label="Smart Tutor, Library">
        <BrandMark size="sm" iconOnly={collapsed} />
      </Link>
      {GROUPS.map((group) => (
        <Fragment key={group}>
          {group > 0 && <hr className={styles.hr} />}
          <ul className={styles.list}>
            {NAV.filter((item) => item.group === group).map(({ path, label, icon: Icon }) => (
              <li key={path}>
                <NavLink
                  className={styles.link}
                  to={path}
                  aria-label={collapsed ? label : undefined}
                  data-tip={collapsed ? label : undefined}
                >
                  <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
                  {!collapsed && <span className={styles.text}>{label}</span>}
                </NavLink>
                {path === "/conversations" && !collapsed && recent.length > 0 && (
                  <ul className={styles.sub} aria-label="Recent conversations">
                    {recent.slice(0, 3).map((c) => (
                      <li key={c.id}>
                        <NavLink to={c.path} title={c.title}>
                          {c.title}
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </Fragment>
      ))}
      <div className={styles.foot}>
        <IconButton
          label={collapsed ? "Expand navigation" : "Collapse navigation"}
          icon={collapsed ? ChevronRight : ChevronLeft}
          aria-expanded={!collapsed}
          onClick={onToggle}
          className={styles.collapse}
        />
        <UserMenu name={name} onSignOut={signOut} compact={collapsed} />
      </div>
    </nav>
  );
}
