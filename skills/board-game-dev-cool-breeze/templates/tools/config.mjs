// Shared public project settings. Private values belong in environment/state.
import { readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
export const project = JSON.parse(readFileSync(process.env.BGD_PROJECT_CONFIG ?? new URL('./project.json', import.meta.url), 'utf8'));
export const runDir = process.env[project.run_dir_env] ?? project.run_dir.replace(/^~(?=\/|$)/, os.homedir());
export const storagePrefix = `${project.name}:`;
