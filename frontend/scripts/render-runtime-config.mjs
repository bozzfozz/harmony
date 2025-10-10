#!/usr/bin/env node
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

function log(level, message, meta = undefined) {
  const payload = {
    level,
    message,
    timestamp: new Date().toISOString(),
  };
  if (meta && Object.keys(meta).length > 0) {
    payload.meta = meta;
  }
  const serialized = JSON.stringify(payload);
  if (level === 'error') {
    console.error(serialized);
  } else if (level === 'warn') {
    console.warn(serialized);
  } else {
    console.log(serialized);
  }
}

function toTemplateString(value) {
  const normalized = value ?? '';
  return JSON.stringify(String(normalized)).slice(1, -1);
}

function parseFeatureFlags(rawValue) {
  if (!rawValue || rawValue.trim().length === 0) {
    return { value: {}, source: 'default-empty' };
  }

  try {
    const parsed = JSON.parse(rawValue);
    if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
      log('warn', 'PUBLIC_FEATURE_FLAGS must be a JSON object; using empty object fallback', {
        providedType: typeof parsed,
      });
      return { value: {}, source: 'fallback-non-object' };
    }
    return { value: parsed, source: 'env' };
  } catch (error) {
    log('warn', 'Failed to parse PUBLIC_FEATURE_FLAGS; using empty object fallback', {
      error: error instanceof Error ? error.message : String(error),
    });
    return { value: {}, source: 'fallback-parse-error' };
  }
}

function applyReplacements(template, replacements) {
  let output = template;
  for (const [placeholder, value] of Object.entries(replacements)) {
    if (!output.includes(placeholder)) {
      throw new Error(`Template placeholder ${placeholder} not found in env.runtime.js.tpl`);
    }
    output = output.replaceAll(placeholder, value);
  }
  return output;
}

async function main() {
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const frontendDir = path.resolve(scriptDir, '..');
  const templatePath = path.join(frontendDir, 'public', 'env.runtime.js.tpl');
  const devOutputPath = path.join(frontendDir, 'public', 'env.runtime.js');
  const distDir = path.join(frontendDir, 'dist');
  const distOutputPath = path.join(distDir, 'env.runtime.js');

  const template = await readFile(templatePath, 'utf8');

  const backendUrl = process.env.PUBLIC_BACKEND_URL ?? '';
  const sentryDsn = process.env.PUBLIC_SENTRY_DSN ?? '';
  const featureFlagsRaw = process.env.PUBLIC_FEATURE_FLAGS ?? '';
  const { value: featureFlags, source: featureFlagsSource } = parseFeatureFlags(featureFlagsRaw);

  const rendered = applyReplacements(template, {
    '${PUBLIC_BACKEND_URL}': toTemplateString(backendUrl),
    '${PUBLIC_SENTRY_DSN}': toTemplateString(sentryDsn),
    '${PUBLIC_FEATURE_FLAGS}': JSON.stringify(featureFlags, null, 2),
  });

  await writeFile(devOutputPath, rendered, 'utf8');
  await mkdir(distDir, { recursive: true });
  await writeFile(distOutputPath, rendered, 'utf8');

  log('info', 'Rendered runtime configuration', {
    outputs: [devOutputPath, distOutputPath],
    featureFlagsSource,
    backendUrlPresent: backendUrl.trim().length > 0,
    sentryDsnPresent: sentryDsn.trim().length > 0,
  });
}

main().catch((error) => {
  log('error', 'Failed to render runtime configuration', {
    error: error instanceof Error ? error.message : String(error),
  });
  process.exitCode = 1;
});
