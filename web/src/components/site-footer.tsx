import styles from "./site.module.css";
import ui from "./ui.module.css";

export function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <div className={`${ui.container} ${styles.footerInner}`}>
        <p>
          Strategies run in your browser with Pyodide and the unmodified <code>prosperity3bt</code> 0.12.0 engine. Your
          files and results never leave your machine.
        </p>
        <p>Synthetic days are calibrated to the QuantiFi round 1 data (days -2, -1 and 0).</p>
      </div>
    </footer>
  );
}
