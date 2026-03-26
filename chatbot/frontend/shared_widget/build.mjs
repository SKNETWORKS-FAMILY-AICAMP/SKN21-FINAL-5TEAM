import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const distDir = path.join(__dirname, 'dist');
const jsOutfile = path.join(distDir, 'widget.js');
const cssOutfile = path.join(distDir, 'widget.css');
const chatbotApiBaseUrl = process.env.NEXT_PUBLIC_CHATBOT_API_URL || 'http://localhost:8100';

await mkdir(distDir, { recursive: true });

await build({
  absWorkingDir: __dirname,
  bundle: true,
  entryPoints: ['widget-entry.ts'],
  define: {
    'process.env.NEXT_PUBLIC_CHATBOT_API_URL': JSON.stringify(chatbotApiBaseUrl),
  },
  format: 'iife',
  jsx: 'automatic',
  loader: {
    '.css': 'css',
  },
  outfile: jsOutfile,
  platform: 'browser',
  sourcemap: false,
  target: ['es2020'],
});

const [bundleSource, cssSource] = await Promise.all([
  readFile(jsOutfile, 'utf-8'),
  readFile(cssOutfile, 'utf-8').catch(() => ''),
]);

const cssPrelude = `globalThis.__ORDER_CS_WIDGET_CSS__ = ${JSON.stringify(cssSource)};\n`;
await writeFile(jsOutfile, `${cssPrelude}${bundleSource}`, 'utf-8');

await rm(cssOutfile, { force: true });
