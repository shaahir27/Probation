import { writeFileSync } from "node:fs";

/** Signals every journey server in this run to shut down. */
export default function stopSyntheticServers() {
  const files: string[] = process.env.PROBATION_D6_E2E_STOP_FILES
    ? (JSON.parse(process.env.PROBATION_D6_E2E_STOP_FILES) as string[])
    : [];
  const single = process.env.PROBATION_D6_E2E_STOP_FILE;
  const targets = files.length > 0 ? files : single ? [single] : [];
  targets.forEach((target) => {
    if (target) writeFileSync(target, "stop", { encoding: "utf8", flag: "w" });
  });
}
