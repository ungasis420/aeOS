/**
 * Icon generation helper — run with Node after installing sharp:
 *   npm install -D sharp
 *   node scripts/gen-icons.js
 *
 * Creates PNG icons at all required sizes from public/icons/favicon.svg.
 * Not a build dependency; run once to generate committed icons.
 */

import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const iconsDir = path.join(__dirname, '../public/icons');
const svgPath  = path.join(iconsDir, 'favicon.svg');

const SIZES = [72, 96, 128, 144, 152, 192, 384, 512];

async function main() {
  let sharp;
  try {
    sharp = require('sharp');
  } catch {
    console.warn('sharp not installed — skipping PNG generation');
    console.warn('Run: npm install -D sharp && node scripts/gen-icons.js');
    process.exit(0);
  }

  const svgBuffer = fs.readFileSync(svgPath);
  for (const size of SIZES) {
    const out = path.join(iconsDir, `icon-${size}.png`);
    await sharp(svgBuffer).resize(size, size).png().toFile(out);
    console.log(`  ✓ icon-${size}.png`);
  }
  console.log('Icons generated.');
}

main().catch(err => { console.error(err); process.exit(1); });
