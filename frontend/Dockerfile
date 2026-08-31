# Development image for the frontend (FE-01, XC-01).
#
# Single-stage dev image running Vite's own dev server (HMR) rather than a
# production build + static-file server -- this is docker-compose.dev.yml,
# not a deployment artifact. A production image (multi-stage: `npm run
# build` -> serve `dist/` from nginx or similar) is a separate concern for
# whenever this project needs one.

FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# `--host 0.0.0.0` is required for the dev server to be reachable from
# outside the container (Vite binds to localhost only by default).
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
