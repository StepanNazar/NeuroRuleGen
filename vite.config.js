import { defineConfig } from 'vite';
import { resolve } from 'node:path';

const root = resolve('src/neurorulegen/user_interface/assets');
const devServer = new URL(process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5173');
const appHost = process.env.APP_HOST || '127.0.0.1';
const appPort = process.env.APP_PORT || '8000';
const appOrigin = process.env.APP_ORIGIN || `http://${appHost}:${appPort}`;
const entries = [
  'main',
  'admin',
  'profile',
  'password_recovery',
  'project_settings',
  'project_overview',
  'analysis_result',
  'run_log',
  'rules',
  'ai_settings',
  'forms',
];
export default defineConfig({
  root,
  base: process.env.NODE_ENV === 'production' ? '/static/dist/' : '/',
  server: {
    host: process.env.VITE_HOST || devServer.hostname,
    port: Number(devServer.port || 5173),
    strictPort: true,
    origin: devServer.origin,
    cors: {
      origin: [
        ...new Set([appOrigin, `http://localhost:${appPort}`, `http://127.0.0.1:${appPort}`]),
      ],
    },
  },
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
    manifest: true,
    rolldownOptions: {
      input: Object.fromEntries(entries.map((name) => [name, resolve(root, `js/${name}.js`)])),
    },
  },
});
