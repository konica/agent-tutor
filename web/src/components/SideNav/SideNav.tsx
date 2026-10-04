import { Link, NavLink } from "react-router";

import { NAV } from "../../app/nav";
import { BrandMark } from "../BrandMark/BrandMark";
import { UserMenu } from "../UserMenu/UserMenu";
import styles from "./SideNav.module.css";

export function SideNav() {
  return (
    <nav className={styles.sidenav} aria-label="Main">
      <Link className={styles.brand} to="/library">
        <BrandMark />
      </Link>
      <ul className={styles.list}>
        {NAV.map(({ path, label, icon: Icon }) => (
          <li key={path}>
            <NavLink className={styles.link} to={path}>
              <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      {/* US-1 replaces the placeholder name and wires Sign out. */}
      <UserMenu name="Learner" />
    </nav>
  );
}
