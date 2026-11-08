// Shared public project settings. Private values belong in environment/state.
import { readFileSync } from 'node:fs';
import os from 'node:os';
export const project = JSON.parse(readFileSync(process.env.BGD_PROJECT_CONFIG ?? new URL('./project.json', import.meta.url), 'utf8'));
export const runDir = process.env[project.run_dir_env] || project.run_dir.replace(/^~(?=\/|$)/, os.homedir());
export const storagePrefix = `${project.name}:`;
export const envPrefix = project.env_prefix ?? 'BGD_';
export const envName = (suffix) => envPrefix + suffix;
