// Entry-point helpers: run main() only when executed directly, print errors without a stack trace.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export const isMain = (metaUrl) => Boolean(process.argv[1]) && metaUrl === pathToFileURL(resolve(process.argv[1])).href;

export function run(main) {
  main().catch((e) => {
    console.error(`error: ${e.message}`);
    process.exit(1);
  });
}
