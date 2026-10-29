// Lets `node --test` load lib/*.ts directly: Node strips the types, and this hook adds the `.ts`
// that the app's extensionless relative imports (resolved by Next's bundler) leave out.

import { registerHooks } from "node:module";

registerHooks({
  resolve(specifier, context, next) {
    try {
      return next(specifier, context);
    } catch (err) {
      if (err?.code !== "ERR_MODULE_NOT_FOUND" || !/^\.{1,2}\//.test(specifier) || specifier.endsWith(".ts")) throw err;
      return next(`${specifier}.ts`, context);
    }
  },
});
